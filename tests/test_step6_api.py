"""
步骤6 - FastAPI 接口层 测试脚本

覆盖（按需求）：
1. 登录鉴权（register/login/me + 无 token/无效 token 拦截）
2. 接口权限拦截（非成员访问知识库 403）
3. 文档异步上传接口（立即返回 task_id，后台向量化不阻塞）
4. RAG 问答接口（answer + citations + 会话消息）
5. Agent 任务提交查询
6. 全局异常返回格式校验（业务异常/参数校验异常的统一 code/message 格式）

设计说明：
- 用 fastapi.testclient.TestClient 直接跑 app（无需起真实服务）
- DB 用 SQLite 共享内存库，覆盖 db.session 引擎并 override get_db 依赖
- 注入 FakeRagPipeline / FakeAgentManager 到 service 单例，离线可跑
- 后台异步任务线程复用同一共享内存库，文档状态用新会话轮询避免缓存

运行方式：
    pip install fastapi uvicorn python-multipart httpx sqlalchemy pydantic bcrypt PyJWT
    python tests/test_step6_api.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.constants import DocumentStatus


# ============================================================
# 测试用 Fake 组件
# ============================================================

class _FakeCitation:
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


class FakeRagPipeline:
    def __init__(self):
        self.ingested = []
        self.version_manager = _FakeVersionManager()

    def ingest_document(self, kb_id, doc_id, document_name, file_path=None, parsed=None):
        self.ingested.append((kb_id, doc_id, document_name))
        return 3

    def answer(self, query, knowledge_base_ids=None, top_k=5, history=None, **kwargs):
        return _FakeRagAnswer()


class _FakeVersionManager:
    def clear_document_chunks(self, collection_name, document_id):
        return None


class _FakeAgentResult:
    def __init__(self, task_id, success):
        self.task_id = task_id
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


class FakeAgentManager:
    """模拟 AgentManager 统一入口（复用 agent_tasks ORM 写任务记录）"""
    def __init__(self, success=True):
        self.success = success
        self._counter = 0

    def execute(self, user_id, task_input, knowledge_base_ids,
                conversation_id=None, db=None, title=None):
        self._counter += 1
        task_id = f"fake_task_{self._counter}"
        if db is not None:
            from db.crud import agent_task_crud
            from db.schemas import AgentTaskCreate
            from config.constants import AgentTaskStatus
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
                agent_task_crud.update_status(db, task_id, AgentTaskStatus.FAILED.value, "失败")
        return _FakeAgentResult(task_id, self.success)


# ============================================================
# 测试环境
# ============================================================

def setup_client():
    """
    初始化文件型 SQLite + override get_db 依赖 + 注入 Fake，返回 TestClient。
    采用 临时文件 + WAL + NullPool 方案，消除主线程与后台线程的并发写锁竞争。
    """
    import tempfile
    import os
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    import db.session as db_session

    tmpdir = tempfile.mkdtemp(prefix="kb_step6_test_")
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

    # override get_db 依赖
    from db.session import get_db
    def override_get_db():
        db = db_session.SyncSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # 注入 Fake 到 service 单例（避免真实模型/向量库/AgentManager）
    from services import document_service, chat_service, agent_service
    document_service.rag_pipeline = FakeRagPipeline()
    chat_service.rag_pipeline = FakeRagPipeline()
    agent_service.agent_manager = FakeAgentManager(success=True)

    from api.main import app
    app.dependency_overrides[get_db] = override_get_db

    from fastapi.testclient import TestClient
    return TestClient(app)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_and_login(client, username):
    client.post("/api/v1/auth/register", json={
        "username": username, "password": "Test@123",
        "email": f"{username}@x.com", "nickname": username,
    })
    r = client.post("/api/v1/auth/login", json={"username": username, "password": "Test@123"})
    return r.json()["data"]


def _doc_status(doc_id):
    from db.session import SyncSessionLocal
    from db.crud import document_crud
    s = SyncSessionLocal()
    try:
        d = document_crud.get_by_id(s, doc_id)
        return d.status if d else None
    finally:
        s.close()


def _wait_ready(doc_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _doc_status(doc_id) == DocumentStatus.READY.value:
            return True
        time.sleep(0.05)
    return False


# ============================================================
# 测试函数
# ============================================================

def test_1_login_auth(client):
    """登录鉴权：注册/登录/me + 无 token/无效 token 拦截"""
    print("\n" + "=" * 60)
    print("【测试1】登录鉴权")
    print("=" * 60)

    # 注册
    r = client.post("/api/v1/auth/register", json={
        "username": "alice", "password": "Secret@1", "email": "alice@x.com",
    })
    assert r.status_code == 200 and r.json()["code"] == 0
    print(f"  ✓ 注册成功: code={r.json()['code']}")

    # 登录
    r = client.post("/api/v1/auth/login", json={"username": "alice", "password": "Secret@1"})
    body = r.json()
    assert body["code"] == 0
    token = body["data"]["access_token"]
    assert body["data"]["token_type"] == "bearer"
    print(f"  ✓ 登录成功: 双令牌签发, token={token[:20]}...")

    # me（带 token）
    r = client.get("/api/v1/auth/me", headers=_auth_header(token))
    assert r.status_code == 200 and r.json()["data"]["username"] == "alice"
    print(f"  ✓ /me 鉴权通过: username={r.json()['data']['username']}")

    # 无 token
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == 1100001  # AUTH_TOKEN_MISSING
    print(f"  ✓ 无 token 拦截: 401, code={r.json()['code']}")

    # 无效 token
    r = client.get("/api/v1/auth/me", headers=_auth_header("invalid.token.here"))
    assert r.status_code == 401
    print(f"  ✓ 无效 token 拦截: 401, code={r.json()['code']}")

    print("  ✅ 登录鉴权 通过")


def test_2_permission_intercept(client):
    """接口权限拦截：非成员访问知识库 403"""
    print("\n" + "=" * 60)
    print("【测试2】接口权限拦截")
    print("=" * 60)

    owner = _register_and_login(client, "kb_owner")
    outsider = _register_and_login(client, "kb_outsider")

    # owner 建库
    r = client.post("/api/v1/kb", json={"name": "权限测试库"},
                    headers=_auth_header(owner["access_token"]))
    kb_id = r.json()["data"]["id"]
    assert r.json()["data"]["user_role"] == "owner"
    print(f"  ✓ owner 创建知识库: kb_id={kb_id}")

    # 非成员访问 → 403
    r = client.get(f"/api/v1/kb/{kb_id}", headers=_auth_header(outsider["access_token"]))
    assert r.status_code == 403
    assert r.json()["code"] == 1200003  # KB_NO_PERMISSION
    print(f"  ✓ 非成员访问拦截: 403, code={r.json()['code']}")

    # 非成员添加成员 → 403
    r = client.post(f"/api/v1/kb/{kb_id}/members", json={"user_id": 1, "role": "read"},
                    headers=_auth_header(outsider["access_token"]))
    assert r.status_code == 403
    print(f"  ✓ 非成员越权加成员拦截: 403")

    print("  ✅ 接口权限拦截 通过")


def test_3_document_upload(client):
    """文档异步上传接口：立即返回 task_id，后台向量化"""
    print("\n" + "=" * 60)
    print("【测试3】文档异步上传接口")
    print("=" * 60)

    owner = _register_and_login(client, "doc_owner")
    r = client.post("/api/v1/kb", json={"name": "文档库"},
                    headers=_auth_header(owner["access_token"]))
    kb_id = r.json()["data"]["id"]

    md = "# 请假流程\n\n员工请假需提前三天提交申请。\n".encode("utf-8")
    r = client.post(
        f"/api/v1/kb/{kb_id}/documents",
        files={"file": ("请假流程.md", md, "text/markdown")},
        headers=_auth_header(owner["access_token"]),
    )
    assert r.status_code == 200 and r.json()["code"] == 0
    data = r.json()["data"]
    doc_id = data["document_id"]
    assert data["task_id"]
    print(f"  ✓ 上传立即返回: doc_id={doc_id}, task_id={data['task_id']}")

    # 后台异步向量化完成
    assert _wait_ready(doc_id), "文档应在超时内完成向量化"
    print(f"  ✓ 后台向量化完成: status=ready")

    # 文档列表
    r = client.get(f"/api/v1/kb/{kb_id}/documents", headers=_auth_header(owner["access_token"]))
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["items"][0]["status"] == "ready"
    print(f"  ✓ 文档列表: total={r.json()['data']['total']}")

    print("  ✅ 文档异步上传接口 通过")


def test_4_rag_chat(client):
    """RAG 问答接口：answer + citations + 会话消息"""
    print("\n" + "=" * 60)
    print("【测试4】RAG 问答接口")
    print("=" * 60)

    owner = _register_and_login(client, "chat_owner")
    r = client.post("/api/v1/kb", json={"name": "问答库"},
                    headers=_auth_header(owner["access_token"]))
    kb_id = r.json()["data"]["id"]

    # 问答
    r = client.post("/api/v1/chat/ask",
                    json={"knowledge_base_id": kb_id, "query": "请假流程是什么？"},
                    headers=_auth_header(owner["access_token"]))
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["answer"]
    assert len(body["data"]["citations"]) == 1
    conv_id = body["data"]["conversation_id"]
    print(f"  ✓ 问答成功: answer={body['data']['answer'][:20]}..., 引用 {len(body['data']['citations'])} 条")

    # 消息列表
    r = client.get(f"/api/v1/chat/conversations/{conv_id}/messages",
                   headers=_auth_header(owner["access_token"]))
    msgs = r.json()["data"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user" and msgs[1]["role"] == "assistant"
    print(f"  ✓ 会话消息: {len(msgs)} 条 (user+assistant)")

    # 会话列表
    r = client.get("/api/v1/chat/conversations", headers=_auth_header(owner["access_token"]))
    assert r.json()["data"]["total"] >= 1
    print(f"  ✓ 会话列表: total={r.json()['data']['total']}")

    print("  ✅ RAG 问答接口 通过")


def test_5_agent_submit(client):
    """Agent 任务提交查询"""
    print("\n" + "=" * 60)
    print("【测试5】Agent 任务提交查询")
    print("=" * 60)

    owner = _register_and_login(client, "agent_owner")
    r = client.post("/api/v1/kb", json={"name": "Agent库"},
                    headers=_auth_header(owner["access_token"]))
    kb_id = r.json()["data"]["id"]

    # 提交
    r = client.post("/api/v1/agent/tasks",
                    json={"knowledge_base_id": kb_id, "task_input": "总结请假流程", "title": "总结"},
                    headers=_auth_header(owner["access_token"]))
    body = r.json()
    assert body["code"] == 0
    task_id = body["data"]["task_id"]
    assert task_id.startswith("fake_task_")
    print(f"  ✓ Agent 任务提交: task_id={task_id}")

    # 列表
    r = client.get("/api/v1/agent/tasks", headers=_auth_header(owner["access_token"]))
    assert r.json()["data"]["total"] >= 1
    print(f"  ✓ 任务列表: total={r.json()['data']['total']}")

    # 详情
    r = client.get(f"/api/v1/agent/tasks/{task_id}", headers=_auth_header(owner["access_token"]))
    assert r.json()["data"]["task_id"] == task_id
    assert r.json()["data"]["status"] == "success"
    print(f"  ✓ 任务详情: status={r.json()['data']['status']}")

    print("  ✅ Agent 任务提交查询 通过")


def test_6_exception_format(client):
    """全局异常返回格式校验"""
    print("\n" + "=" * 60)
    print("【测试6】全局异常返回格式校验")
    print("=" * 60)

    # 业务异常（登录失败 → 401，统一 code/message 结构）
    r = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "wrong"})
    body = r.json()
    assert r.status_code == 401
    assert body["code"] == 1100004  # AUTH_CREDENTIALS_ERROR
    assert set(body.keys()) >= {"code", "message", "data", "timestamp"}
    print(f"  ✓ 业务异常格式: code={body['code']}, message={body['message']}")

    # 参数校验异常（用户名过短 → 422）
    r = client.post("/api/v1/auth/register", json={"username": "ab", "password": "123456"})
    body = r.json()
    assert r.status_code == 422
    assert body["code"] == 1000002  # INVALID_PARAMS
    assert set(body.keys()) >= {"code", "message", "data", "timestamp"}
    print(f"  ✓ 校验异常格式: code={body['code']}, message={body['message']}")

    # 框架级 404（未知路径）
    r = client.get("/api/v1/not-exist")
    assert r.status_code == 404
    assert "code" in r.json()
    print(f"  ✓ 框架 404 格式: code={r.json()['code']}")

    print("  ✅ 全局异常返回格式校验 通过")


def main():
    print("\n" + "🚀" * 10 + " 步骤6 FastAPI 接口层测试开始 " + "🚀" * 10)

    client = setup_client()

    tests = [
        test_1_login_auth,
        test_2_permission_intercept,
        test_3_document_upload,
        test_4_rag_chat,
        test_5_agent_submit,
        test_6_exception_format,
    ]

    passed = 0
    failed = 0
    for test_func in tests:
        try:
            test_func(client)
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
        print("🎉 全部测试通过！步骤6 FastAPI 接口层正常。")
        print()
        print("✅ 关键能力验证:")
        print("   JWT 鉴权依赖（access_token 解析当前用户 + 无/无效 token 拦截）")
        print("   接口权限拦截（非成员访问知识库 403）")
        print("   文档异步上传（立即返回 task_id，后台向量化不阻塞）")
        print("   RAG 问答接口（answer + citations + 会话消息）")
        print("   Agent 任务提交查询")
        print("   全局异常统一返回格式（业务/校验/404）")
    else:
        print(f"⚠️  有 {failed} 项测试失败。")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
