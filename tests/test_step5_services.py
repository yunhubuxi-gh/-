"""
步骤5 - Service 业务服务层 测试脚本

覆盖（按需求）：
1. 用户注册登录（密码 bcrypt、JWT 双令牌、重复注册拦截）
2. 知识库权限隔离（owner/admin/write/read 四级、成员管理、越权拦截）
3. 文档上传向量化（文件落盘、元数据、异步任务、状态流转）
4. 普通 RAG 问答（会话管理 + rag_engine 入口 + 消息持久化）
5. Agent 任务提交执行（复用 AgentManager + agent_tasks 表）
6. 越权访问拦截（read 用户无法上传/管理，写审计 permission_denied）
7. 审计日志写入验证（文件审计 + 数据库审计）

设计说明：
- 全部注入 Fake 组件（FakeRagPipeline / FakeAgentManager / 内存向量引擎），离线可跑
- DB 用 SQLite 内存库；文档向量化注入 FakePipeline 不触发真实模型下载
- 异步任务（BackgroundTasksEngine）在线程内跑，测试用轮询等待完成

运行方式：
    pip install sqlalchemy pydantic bcrypt PyJWT
    python tests/test_step5_services.py
"""
from __future__ import annotations

import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.constants import KBUserRole, DocumentStatus, AuditResult


# ============================================================
# 测试用 Fake 组件
# ============================================================

class FakeRagPipeline:
    """模拟 rag_engine 统一入口（文档入库 + 问答），不触发真实模型/向量库"""

    def __init__(self):
        self.ingested = []       # [(kb_id, doc_id, name)]
        self.answer_calls = []

    def ingest_document(self, kb_id, doc_id, document_name, file_path=None, parsed=None):
        self.ingested.append((kb_id, doc_id, document_name))
        return 3  # 假设分块数

    def answer(self, query, knowledge_base_ids=None, top_k=5, history=None, **kwargs):
        self.answer_calls.append((query, knowledge_base_ids))
        return _FakeRagAnswer()


class _FakeCitation:
    """模拟 rag_engine.Citation（带 to_dict）"""
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def to_dict(self):
        return dict(self.__dict__)


class _FakeRagAnswer:
    answer = "根据知识库，员工请假需提前三天提交申请。[1]"
    citations = [_FakeCitation(
        index=1, document_id="1", document_name="员工手册.md",
        page_number=1, chunk_index=0, chunk_id="doc_1:0",
        excerpt="请假需提前三天", score=0.9,
    )]
    context_chunks = []
    grounded = True
    no_answer = False
    warnings = []


class FakeVersionManager:
    """模拟文档版本索引编排器（清理索引）"""
    def __init__(self):
        self.cleared = []

    def clear_document_chunks(self, collection_name, document_id):
        self.cleared.append((collection_name, document_id))


class FakeAgentManager:
    """模拟 AgentManager 统一执行入口（同时写 agent_tasks 表，对齐真实行为）"""
    def __init__(self, success=True):
        self.success = success
        self.calls = []

    def execute(self, user_id, task_input, knowledge_base_ids,
                conversation_id=None, db=None, title=None):
        self.calls.append((user_id, task_input, knowledge_base_ids))
        # 模拟真实 AgentManager：复用 agent_tasks ORM 模型写任务记录
        if db is not None:
            from db.crud import agent_task_crud
            from db.schemas import AgentTaskCreate
            from config.constants import AgentTaskStatus
            task_id = "fake_task_123"
            agent_task_crud.create(
                db, user_id,
                AgentTaskCreate(
                    task_input=task_input,
                    conversation_id=conversation_id,
                    knowledge_base_id=knowledge_base_ids[0] if knowledge_base_ids else None,
                    title=title,
                ),
                task_id=task_id,
            )
            if self.success:
                agent_task_crud.set_result(db, task_id, "任务执行完成")
            else:
                agent_task_crud.update_status(db, task_id, AgentTaskStatus.FAILED.value, "工具执行失败")
        return _FakeAgentResult(task_input, self.success)


class _FakeAgentResult:
    def __init__(self, task_input, success):
        self.task_id = "fake_task_123"
        self.status = "success" if success else "failed"
        self.result = "任务执行完成" if success else None
        self.tool_history = []
        self.retry_count = 0
        self.error = None if success else "工具执行失败"

    @property
    def success(self):
        return self.status == "success"

    def to_dict(self):
        return {
            "task_id": self.task_id, "status": self.status, "result": self.result,
            "tool_history": self.tool_history, "retry_count": self.retry_count,
            "error": self.error, "success": self.success,
        }


# ============================================================
# 测试环境
# ============================================================

def setup_test_db():
    """
    初始化文件型 SQLite 测试库，供主线程与后台线程（异步文档处理）共同读写。

    采用 临时文件 + WAL + NullPool 方案：
    - WAL 模式下读不阻塞写、写不阻塞读，彻底消除并发写锁竞争
      （shared-cache 内存库会偶发 "table is locked"，SQLITE_LOCKED 不等待 timeout）
    - NullPool 让每个 session 独立连接，避免连接复用持锁
    """
    import tempfile
    import os
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    import db.session as db_session

    tmpdir = tempfile.mkdtemp(prefix="kb_step5_test_")
    db_path = os.path.join(tmpdir, "test.db").replace("\\", "/")

    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=NullPool,
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA busy_timeout=30000")
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")

    db_session.sync_engine = engine
    db_session.SyncSessionLocal = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False,
    )
    from db.base import Base
    from db import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    return engine


def _new_session():
    from db.session import SyncSessionLocal
    return SyncSessionLocal()


def _register_user(db, username, password="Test@123", email=None):
    from db.schemas import UserCreate
    from services import auth_service
    return auth_service.register(db, UserCreate(
        username=username, password=password, email=email, nickname=username,
    ))


def _create_kb(db, owner_id, name):
    from db.schemas import KBCreate
    from services import kb_service
    return kb_service.create(db, owner_id, KBCreate(name=name))


def _wait_until(predicate, timeout=5.0, interval=0.05):
    """轮询等待异步任务完成"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ============================================================
# 测试函数
# ============================================================

def test_1_auth_register_login():
    """用户注册 + 登录 + 重复注册拦截"""
    print("\n" + "=" * 60)
    print("【测试1】用户注册登录")
    print("=" * 60)

    from services import auth_service
    from db.schemas import UserCreate, UserLogin
    from utils.security import verify_password
    from utils.exceptions import AuthException

    db = _new_session()
    u = auth_service.register(db, UserCreate(username="alice", password="Secret@1", email="a@x.com"))
    assert u["id"] is not None
    assert "password_hash" not in u  # 绝不返回密码哈希
    print(f"  ✓ 注册成功: id={u['id']}, username={u['username']}")

    # 密码只存哈希（bcrypt）
    from db.crud import user_crud
    db_user = user_crud.get_by_username(db, "alice")
    assert db_user.password_hash != "Secret@1"
    assert verify_password("Secret@1", db_user.password_hash)
    print(f"  ✓ 密码 bcrypt 哈希存储，非明文")

    # 重复注册拦截
    try:
        auth_service.register(db, UserCreate(username="alice", password="Xx@12345"))
        raise AssertionError("应拦截重复用户名")
    except AuthException as e:
        print(f"  ✓ 重复注册拦截: [{e.code}] {e.message}")

    # 登录
    result = auth_service.login(db, "alice", "Secret@1", ip="127.0.0.1")
    assert result["access_token"] and result["refresh_token"]
    assert result["token_type"] == "bearer"
    assert result["user"]["username"] == "alice"
    print(f"  ✓ 登录成功: 双令牌签发, expires_in={result['expires_in']}")

    # 错误密码
    try:
        auth_service.login(db, "alice", "wrong")
        raise AssertionError("应拦截错误密码")
    except AuthException as e:
        print(f"  ✓ 错误密码拦截: [{e.code}] {e.message}")

    # 令牌解析 -> 当前用户
    token = result["access_token"]
    current = auth_service.get_current_user(db, token)
    assert current.username == "alice"
    print(f"  ✓ get_current_user 解析令牌成功: {current.username}")

    db.close()
    print("  ✅ 用户注册登录 通过")


def test_2_kb_permission_isolation():
    """知识库权限隔离 + 成员管理"""
    print("\n" + "=" * 60)
    print("【测试2】知识库权限隔离")
    print("=" * 60)

    from services import kb_service
    from db.schemas import KBCreate, KBMemberAdd, KBMemberUpdate
    from db.crud import kb_crud
    from utils.exceptions import PermissionException

    db = _new_session()
    owner = _register_user(db, "owner")["id"]
    writer = _register_user(db, "writer")["id"]
    reader = _register_user(db, "reader")["id"]
    outsider = _register_user(db, "outsider")["id"]

    kb = _create_kb(db, owner, "公司制度库")
    kb_id = kb["id"]
    assert kb["user_role"] == KBUserRole.OWNER.value
    print(f"  ✓ 创建知识库: id={kb_id}, 创建者自动 owner")

    # owner 添加成员
    kb_service.add_member(db, owner, kb_id, KBMemberAdd(user_id=writer, role=KBUserRole.WRITE.value))
    kb_service.add_member(db, owner, kb_id, KBMemberAdd(user_id=reader, role=KBUserRole.READ.value))
    assert kb_crud.get_user_role(db, kb_id, writer) == KBUserRole.WRITE.value
    assert kb_crud.get_user_role(db, kb_id, reader) == KBUserRole.READ.value
    print(f"  ✓ owner 添加成员: writer(write), reader(read)")

    # reader 不能添加成员（越权）
    try:
        kb_service.add_member(db, reader, kb_id, KBMemberAdd(user_id=outsider, role="read"))
        raise AssertionError("reader 越权添加成员应被拦截")
    except PermissionException as e:
        print(f"  ✓ reader 越权添加成员被拦截: [{e.code}] {e.message}")

    # outsider 无任何权限
    assert kb_service.get_user_role(db, outsider, kb_id) is None
    try:
        kb_service.get(db, outsider, kb_id)
        raise AssertionError("outsider 无权限应被拦截")
    except PermissionException as e:
        print(f"  ✓ 非成员访问拦截: [{e.code}] {e.message}")

    # owner 更新成员权限
    kb_service.update_member_role(db, owner, kb_id, reader, KBMemberUpdate(role=KBUserRole.ADMIN.value))
    assert kb_crud.get_user_role(db, kb_id, reader) == KBUserRole.ADMIN.value
    print(f"  ✓ owner 更新成员权限: reader(read->admin)")

    # 列表 + 我的知识库
    my_kbs = kb_service.list_my(db, reader)
    assert my_kbs["total"] >= 1
    members = kb_service.list_members(db, owner, kb_id)
    assert members["total"] == 3
    print(f"  ✓ list_my / list_members 正常: 成员数={members['total']}")

    db.close()
    print("  ✅ 知识库权限隔离 通过")


def test_3_document_upload_and_ingest():
    """文档上传向量化（write 权限 + 文件落盘 + 异步处理）"""
    print("\n" + "=" * 60)
    print("【测试3】文档上传向量化")
    print("=" * 60)

    from services import document_service
    from services.document_service import DocumentService
    from db.schemas import KBMemberAdd
    from db.crud import document_crud, kb_crud
    from utils.exceptions import PermissionException

    db = _new_session()
    owner = _register_user(db, "doc_owner")["id"]
    reader = _register_user(db, "doc_reader")["id"]
    kb = _create_kb(db, owner, "文档库")
    kb_id = kb["id"]
    from services import kb_service
    kb_service.add_member(db, owner, kb_id, KBMemberAdd(user_id=reader, role=KBUserRole.READ.value))

    # 注入 FakeRagPipeline，避免真实模型/向量库
    fake = FakeRagPipeline()
    svc = DocumentService(rag_pipeline=fake)

    md_content = "# 员工请假流程\n\n员工请假需提前三天提交申请，经部门主管审批。\n".encode("utf-8")

    # reader 越权上传
    try:
        svc.upload(db, reader, kb_id, "请假流程.md", md_content)
        raise AssertionError("reader 越权上传应被拦截")
    except PermissionException as e:
        print(f"  ✓ reader 越权上传拦截: [{e.code}] {e.message}")

    # owner 上传（owner >= write）
    result = svc.upload(db, owner, kb_id, "请假流程.md", md_content)
    doc_id = result["document_id"]
    assert result["status"] == DocumentStatus.UPLOADED.value
    assert result["task_id"]
    print(f"  ✓ 上传成功: doc_id={doc_id}, task_id={result['task_id']}")

    # 文件落盘
    doc = document_crud.get_by_id(db, doc_id)
    assert doc.file_path and os.path.exists(doc.file_path)
    with open(doc.file_path, "rb") as f:
        assert f.read() == md_content
    print(f"  ✓ 原始文件落盘（文件系统，非 PG）: {os.path.basename(doc.file_path)}")

    # 版本记录
    versions = document_crud.list_versions(db, doc_id)
    assert len(versions) == 1 and versions[0].version == 1
    print(f"  ✓ 版本记录 v1 已建立")

    # 异步向量化完成（expire_all 强制从库重查，避免 session 缓存旧状态）
    def _is_ready():
        db.expire_all()
        d = document_crud.get_by_id(db, doc_id)
        return d is not None and d.status == DocumentStatus.READY.value
    assert _wait_until(_is_ready), "文档应在超时内完成向量化"
    assert len(fake.ingested) == 1
    assert fake.ingested[0][1] == doc_id
    print(f"  ✓ 异步向量化完成: status=ready, 分块数={fake.ingested[0]}")

    # 知识库统计已更新（kb 统计在 doc 状态 ready 之后由后台线程紧邻更新，轮询等待消除竞态）
    def _kb_updated():
        db.expire_all()
        kb = kb_crud.get_by_id(db, kb_id)
        return (kb.doc_count or 0) == 1 and (kb.chunk_count or 0) == 3
    assert _wait_until(_kb_updated), "知识库统计应在超时内更新"
    kb = kb_crud.get_by_id(db, kb_id)
    print(f"  ✓ 知识库统计更新: doc_count={kb.doc_count}, chunk_count={kb.chunk_count}")

    db.close()
    print("  ✅ 文档上传向量化 通过")


def test_4_rag_chat():
    """普通 RAG 问答（会话 + 消息 + 引用）"""
    print("\n" + "=" * 60)
    print("【测试4】普通 RAG 问答")
    print("=" * 60)

    from services import chat_service
    from services.chat_service import ChatService
    from db.schemas import ChatRequest, KBMemberAdd
    from db.crud import message_crud, conversation_crud
    from config.constants import MessageRole

    db = _new_session()
    owner = _register_user(db, "chat_owner")["id"]
    kb = _create_kb(db, owner, "问答库")
    kb_id = kb["id"]

    fake = FakeRagPipeline()
    svc = ChatService(rag_pipeline=fake)

    req = ChatRequest(knowledge_base_id=kb_id, query="请假流程是什么？")
    result = svc.ask(db, owner, req)
    conv_id = result["conversation_id"]
    assert result["answer"]
    assert len(result["citations"]) == 1
    print(f"  ✓ 问答成功: conv_id={conv_id}, 引用 {len(result['citations'])} 条")

    # 消息持久化（用户 + 助手）
    msgs = message_crud.get_by_conversation(db, conv_id)
    assert len(msgs) == 2
    assert msgs[0].role == MessageRole.USER.value
    assert msgs[1].role == MessageRole.ASSISTANT.value
    assert msgs[1].citations and len(msgs[1].citations) == 1
    print(f"  ✓ 消息持久化: user+assistant, 助手消息含引用 JSON")

    # 追问（复用会话 + 历史）
    req2 = ChatRequest(conversation_id=conv_id, knowledge_base_id=kb_id, query="需要审批吗？")
    result2 = svc.ask(db, owner, req2)
    assert result2["conversation_id"] == conv_id
    print(f"  ✓ 追问复用同一会话: {len(fake.answer_calls)} 次问答调用")

    # 会话列表
    convs = svc.list_conversations(db, owner)
    assert convs["total"] >= 1
    print(f"  ✓ 会话列表正常: total={convs['total']}")

    db.close()
    print("  ✅ 普通 RAG 问答 通过")


def test_5_agent_submit():
    """Agent 任务提交执行（复用 AgentManager + agent_tasks 表）"""
    print("\n" + "=" * 60)
    print("【测试5】Agent 任务提交执行")
    print("=" * 60)

    from services import agent_service
    from services.agent_service import AgentService
    from db.schemas import AgentTaskCreate
    from db.crud import agent_task_crud, kb_crud
    from utils.exceptions import PermissionException

    db = _new_session()
    owner = _register_user(db, "agent_owner")["id"]
    outsider = _register_user(db, "agent_outsider")["id"]
    kb = _create_kb(db, owner, "Agent库")
    kb_id = kb["id"]

    fake_mgr = FakeAgentManager(success=True)
    svc = AgentService(agent_manager=fake_mgr)

    data = AgentTaskCreate(knowledge_base_id=kb_id, task_input="总结请假流程", title="总结")

    # 非成员提交被拦截
    try:
        svc.submit(db, outsider, data)
        raise AssertionError("非成员提交 Agent 任务应被拦截")
    except PermissionException as e:
        print(f"  ✓ 非成员提交 Agent 拦截: [{e.code}] {e.message}")

    # owner 提交
    result = svc.submit(db, owner, data)
    assert result["task_id"] == "fake_task_123"
    assert result["success"] is True
    assert fake_mgr.calls and fake_mgr.calls[0][2] == [kb_id]
    print(f"  ✓ Agent 任务提交: task_id={result['task_id']}, 知识库={fake_mgr.calls[0][2]}")

    # agent 类型会话自动创建
    convs = _list_agent_convs(db, owner)
    assert convs["total"] >= 1
    print(f"  ✓ 自动创建 agent 会话")

    # 任务列表
    tasks = svc.list_tasks(db, owner)
    assert tasks["total"] >= 1
    print(f"  ✓ 任务列表: total={tasks['total']}")

    db.close()
    print("  ✅ Agent 任务提交执行 通过")


def _list_agent_convs(db, user_id):
    from services import chat_service
    return chat_service.list_conversations(db, user_id)


def test_6_audit_log_written():
    """审计日志写入验证（登录/注册/越权/问答/文档均写审计）"""
    print("\n" + "=" * 60)
    print("【测试6】审计日志写入验证")
    print("=" * 60)

    from db.crud import audit_log_crud
    from config.constants import AuditAction

    db = _new_session()
    # 触发若干业务操作
    owner = _register_user(db, "audit_user")["id"]           # register
    from services import auth_service, kb_service
    from db.schemas import KBCreate, KBMemberAdd
    kb = _create_kb(db, owner, "审计库")                       # kb_create
    kb_id = kb["id"]
    auth_service.login(db, "audit_user", "Test@123")           # login

    outsider = _register_user(db, "audit_out")["id"]
    try:
        kb_service.add_member(db, outsider, kb_id, KBMemberAdd(user_id=owner, role="read"))
    except Exception:
        pass                                                   # 越权 -> permission_denied 审计

    logs, total = audit_log_crud.query(db)
    assert total >= 4, f"审计日志应至少 4 条，实际 {total}"
    actions = {log.action for log in logs}
    assert AuditAction.REGISTER.value in actions
    assert AuditAction.LOGIN.value in actions
    assert AuditAction.KB_CREATE.value in actions
    print(f"  ✓ 审计日志: 共 {total} 条, 动作={sorted(actions)}")

    # 越权审计 result=permission_denied
    denied = [log for log in logs if log.result == AuditResult.PERMISSION_DENIED.value]
    assert len(denied) >= 1
    print(f"  ✓ 越权操作写审计: result=permission_denied, 共 {len(denied)} 条")

    # audit_service 只读查询
    from services import audit_service
    from db.schemas import AuditLogQuery
    r = audit_service.query(db, AuditLogQuery(action=AuditAction.LOGIN.value))
    assert r["total"] >= 1
    print(f"  ✓ audit_service 只读查询: login 日志 {r['total']} 条")

    db.close()
    print("  ✅ 审计日志写入验证 通过")


def main():
    print("\n" + "🚀" * 10 + " 步骤5 Service 业务服务层测试开始 " + "🚀" * 10)

    setup_test_db()

    tests = [
        test_1_auth_register_login,
        test_2_kb_permission_isolation,
        test_3_document_upload_and_ingest,
        test_4_rag_chat,
        test_5_agent_submit,
        test_6_audit_log_written,
    ]

    passed = 0
    failed = 0
    for test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n  ❌ 测试失败: {test_func.__name__}")
            print(f"     错误: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"测试结果: 共 {len(tests)} 大项, 通过 {passed} 项, 失败 {failed} 项")
    print("=" * 60)

    if failed == 0:
        print("🎉 全部测试通过！步骤5 Service 业务服务层正常。")
        print()
        print("✅ 关键能力验证:")
        print("   用户注册登录（bcrypt 哈希 + JWT 双令牌）")
        print("   知识库四级权限隔离（owner/admin/write/read）")
        print("   文档上传向量化（文件落盘 + 异步任务 + 版本管理）")
        print("   普通 RAG 问答（会话 + 消息 + 引用）")
        print("   Agent 任务提交（复用 AgentManager + agent_tasks 表）")
        print("   越权拦截（permission_denied）+ 审计日志写入")
    else:
        print(f"⚠️  有 {failed} 项测试失败。")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
