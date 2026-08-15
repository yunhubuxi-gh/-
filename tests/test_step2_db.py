"""
步骤2 - 数据库层 测试脚本

运行方式：
    pip install sqlalchemy python-dotenv pydantic-settings bcrypt python-jose jieba
    python tests/test_step2_db.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def setup_test_db():
    """初始化测试数据库（SQLite 内存库）"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # 使用内存 SQLite，不影响真实数据
    engine = create_engine("sqlite:///:memory:", echo=False, connect_args={"check_same_thread": False})

    # 覆盖 session 中的引擎
    import db.session as db_session
    db_session.sync_engine = engine
    db_session.SyncSessionLocal = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )

    # 创建所有表
    from db.base import Base
    from db import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    return engine


def test_1_user_crud():
    """测试用户 CRUD"""
    print("\n" + "=" * 60)
    print("【测试1】用户 CRUD")
    print("=" * 60)

    from db.crud import user_crud
    from db.schemas import UserCreate, UserUpdate
    from db.session import SyncSessionLocal
    from utils.security import verify_password

    db = SyncSessionLocal()

    # 创建
    user = user_crud.create(db, UserCreate(
        username="testuser",
        password="Test@123",
        email="test@example.com",
        nickname="测试用户",
    ))
    assert user.id is not None
    assert user.username == "testuser"
    assert user.password_hash != "Test@123"  # 不是明文！
    assert verify_password("Test@123", user.password_hash)
    print(f"  ✓ 创建用户: id={user.id}, username={user.username}")

    # 查询
    u = user_crud.get_by_id(db, user.id)
    assert u is not None
    assert u.username == "testuser"
    print(f"  ✓ 根据ID查询: {u.username}")

    u2 = user_crud.get_by_username(db, "testuser")
    assert u2 is not None
    print(f"  ✓ 根据用户名查询: {u2.username}")

    # 更新
    updated = user_crud.update(db, user.id, UserUpdate(nickname="新昵称"))
    assert updated.nickname == "新昵称"
    print(f"  ✓ 更新昵称: {updated.nickname}")

    # 修改密码
    user_crud.update_password(db, user.id, "NewPass@456")
    u3 = user_crud.get_by_id(db, user.id)
    assert verify_password("NewPass@456", u3.password_hash)
    print(f"  ✓ 修改密码成功")

    # 列表
    users, total = user_crud.get_list(db, keyword="test")
    assert total >= 1
    print(f"  ✓ 列表查询: 共 {total} 条")

    # 删除
    result = user_crud.delete(db, user.id)
    assert result
    u_deleted = user_crud.get_by_id(db, user.id)
    assert u_deleted is None  # 软删除后查不到
    print(f"  ✓ 软删除成功")

    db.close()
    print("  ✅ 用户 CRUD 全部通过")


def test_2_kb_and_permission():
    """测试知识库 + 权限隔离"""
    print("\n" + "=" * 60)
    print("【测试2】知识库 CRUD + 权限隔离")
    print("=" * 60)

    from db.crud import user_crud, kb_crud
    from db.schemas import UserCreate, KBCreate, KBUpdate, KBMemberAdd, KBMemberUpdate
    from db.session import SyncSessionLocal
    from config.constants import KBUserRole

    db = SyncSessionLocal()

    # 先创建两个用户
    owner = user_crud.create(db, UserCreate(username="owner", password="123456"))
    member = user_crud.create(db, UserCreate(username="member", password="123456"))
    outsider = user_crud.create(db, UserCreate(username="outsider", password="123456"))
    print(f"  ✓ 创建用户: owner(id={owner.id}), member(id={member.id}), outsider(id={outsider.id})")

    # 创建知识库（owner 创建）
    kb = kb_crud.create(db, KBCreate(name="测试知识库", description="描述"), owner_id=owner.id)
    assert kb.id is not None
    assert kb.owner_id == owner.id
    assert kb.vector_collection == f"kb_{kb.id}"
    print(f"  ✓ 创建知识库: id={kb.id}, name={kb.name}, vector_collection={kb.vector_collection}")

    # 验证 owner 自动加入授权表
    role = kb_crud.get_user_role(db, kb.id, owner.id)
    assert role == KBUserRole.OWNER.value
    print(f"  ✓ 创建者自动成为 owner: role={role}")

    # 添加成员（read 权限）
    kb_crud.add_member(db, kb.id, KBMemberAdd(user_id=member.id, role=KBUserRole.READ.value))
    member_role = kb_crud.get_user_role(db, kb.id, member.id)
    assert member_role == KBUserRole.READ.value
    print(f"  ✓ 添加成员: member 的角色 = {member_role}")

    # 权限校验
    assert kb_crud.has_access(db, kb.id, owner.id)
    assert kb_crud.has_access(db, kb.id, member.id)
    assert not kb_crud.has_access(db, kb.id, outsider.id)  # 局外人无权
    print(f"  ✓ 权限隔离正确: 局外人无访问权限")

    # 权限级别判断
    from utils.permission import can_write, can_read, can_manage
    assert kb_crud.check_user_role(db, kb.id, owner.id, KBUserRole.ADMIN.value)
    assert not kb_crud.check_user_role(db, kb.id, member.id, KBUserRole.WRITE.value)  # read < write
    print(f"  ✓ 权限级别判断正确")

    # 用户知识库列表
    kbs, total = kb_crud.get_list_by_user(db, member.id)
    assert total == 1
    print(f"  ✓ member 可看到 {total} 个知识库")

    kbs2, total2 = kb_crud.get_list_by_user(db, outsider.id)
    assert total2 == 0
    print(f"  ✓ outsider 可看到 {total2} 个知识库（权限隔离生效）")

    # 更新成员权限为 write
    kb_crud.update_member_role(db, kb.id, member.id, KBMemberUpdate(role=KBUserRole.WRITE.value))
    role_after = kb_crud.get_user_role(db, kb.id, member.id)
    assert role_after == KBUserRole.WRITE.value
    print(f"  ✓ 成员权限升级为: {role_after}")

    # 移除成员
    kb_crud.remove_member(db, kb.id, member.id)
    assert kb_crud.get_user_role(db, kb.id, member.id) is None
    print(f"  ✓ 移除成员成功")

    # 删除知识库
    kb_crud.delete(db, kb.id)
    assert kb_crud.get_by_id(db, kb.id) is None
    print(f"  ✓ 删除知识库成功")

    db.close()
    print("  ✅ 知识库 + 权限隔离全部通过")


def test_3_document_crud():
    """测试文档元数据 CRUD（验证不存正文、不存向量）"""
    print("\n" + "=" * 60)
    print("【测试3】文档元数据 CRUD")
    print("=" * 60)

    from db.crud import user_crud, kb_crud, document_crud
    from db.schemas import UserCreate, KBCreate
    from db.session import SyncSessionLocal
    from config.constants import DocumentStatus, DocumentType

    db = SyncSessionLocal()

    user = user_crud.create(db, UserCreate(username="docuser", password="123456"))
    kb = kb_crud.create(db, KBCreate(name="文档测试库"), owner_id=user.id)

    # 验证 documents 表没有 content / embedding 字段
    from db.models import Document
    doc_columns = [c.name for c in Document.__table__.columns]
    forbidden = ["content", "embedding", "body", "text_content", "vector"]
    for field in forbidden:
        assert field not in doc_columns, f"⚠️  文档表不应包含 {field} 字段！违反三者分离原则！"
    print(f"  ✓ 文档表字段合规（无正文、无向量，遵守三者分离原则）")
    print(f"    字段列表: {doc_columns}")

    # 创建文档
    doc = document_crud.create(
        db,
        kb_id=kb.id,
        uploader_id=user.id,
        title="测试文档.pdf",
        file_name="测试文档.pdf",
        file_path="/data/uploads/kb_1/abc123.pdf",
        file_size=102400,
        doc_type=DocumentType.PDF.value,
        file_hash="sha256dummyhash123",
    )
    assert doc.id is not None
    assert doc.status == DocumentStatus.UPLOADED.value
    assert doc.file_path is not None  # 只存路径，不存内容
    print(f"  ✓ 创建文档: id={doc.id}, status={doc.status}")

    # 更新状态（模拟处理流程）
    document_crud.update_status(db, doc.id, DocumentStatus.PARSING.value)
    document_crud.update_status(db, doc.id, DocumentStatus.EMBEDDING.value)
    document_crud.update_stats(db, doc.id, page_count=10, char_count=5000, chunk_count=20)
    document_crud.update_status(db, doc.id, DocumentStatus.READY.value)

    doc_ready = document_crud.get_by_id(db, doc.id)
    assert doc_ready.status == DocumentStatus.READY.value
    assert doc_ready.page_count == 10
    assert doc_ready.chunk_count == 20
    print(f"  ✓ 文档状态流转: uploaded → parsing → embedding → ready")
    print(f"    统计: {doc_ready.page_count}页, {doc_ready.char_count}字, {doc_ready.chunk_count}块")

    # 版本管理
    ver = document_crud.add_version(
        db, doc_id=doc.id, version=2, file_path="/path/to/v2.pdf",
        file_hash="hashv2", file_size=204800, uploaded_by=user.id,
        change_log="更新内容",
    )
    assert ver.version == 2
    versions = document_crud.list_versions(db, doc.id)
    assert len(versions) == 1
    print(f"  ✓ 文档版本管理: 新增 version={ver.version}, 共 {len(versions)} 个版本")

    # 列表查询
    docs, total = document_crud.get_list_by_kb(db, kb.id, status=DocumentStatus.READY.value)
    assert total == 1
    print(f"  ✓ 列表查询: 就绪文档 {total} 个")

    # 删除
    document_crud.delete(db, doc.id)
    assert document_crud.get_by_id(db, doc.id) is None
    print(f"  ✓ 删除文档成功")

    db.close()
    print("  ✅ 文档元数据 CRUD 全部通过")


def test_4_conversation_message():
    """测试会话与消息"""
    print("\n" + "=" * 60)
    print("【测试4】会话 + 消息 CRUD")
    print("=" * 60)

    from db.crud import user_crud, kb_crud, conversation_crud, message_crud
    from db.schemas import UserCreate, KBCreate, ConversationCreate
    from db.session import SyncSessionLocal
    from config.constants import ConversationType, MessageRole

    db = SyncSessionLocal()

    user = user_crud.create(db, UserCreate(username="chatuser", password="123456"))
    kb = kb_crud.create(db, KBCreate(name="对话测试库"), owner_id=user.id)

    # 创建会话
    conv = conversation_crud.create(db, user.id, ConversationCreate(
        title="测试会话",
        knowledge_base_id=kb.id,
        type=ConversationType.CHAT.value,
    ))
    assert conv.id is not None
    print(f"  ✓ 创建会话: id={conv.id}, type={conv.type}")

    # 发送消息
    msg1 = message_crud.create(db, conv.id, MessageRole.USER.value, "你好")
    msg2 = message_crud.create(db, conv.id, MessageRole.ASSISTANT.value, "你好！有什么可以帮你的？",
                                citations=[{"doc": "test.pdf", "page": 1}])
    print(f"  ✓ 创建消息: user + assistant 两条")

    # 获取消息列表
    msgs = message_crud.get_by_conversation(db, conv.id)
    assert len(msgs) == 2
    assert msgs[0].role == MessageRole.USER.value
    print(f"  ✓ 获取历史消息: {len(msgs)} 条")

    # 会话统计
    conv2 = conversation_crud.get_by_id(db, conv.id)
    assert conv2.message_count == 2
    assert conv2.last_message_at is not None
    print(f"  ✓ 会话统计更新: message_count={conv2.message_count}")

    # 会话列表
    convs, total = conversation_crud.get_list_by_user(db, user.id)
    assert total == 1
    print(f"  ✓ 用户会话列表: {total} 个")

    # 删除会话
    conversation_crud.delete(db, conv.id)
    assert conversation_crud.get_by_id(db, conv.id) is None
    print(f"  ✓ 删除会话成功")

    db.close()
    print("  ✅ 会话 + 消息 CRUD 全部通过")


def test_5_agent_task():
    """测试 Agent 任务"""
    print("\n" + "=" * 60)
    print("【测试5】Agent 任务 CRUD")
    print("=" * 60)

    from db.crud import user_crud, agent_task_crud
    from db.schemas import UserCreate, AgentTaskCreate
    from db.session import SyncSessionLocal
    from config.constants import AgentTaskStatus

    db = SyncSessionLocal()

    user = user_crud.create(db, UserCreate(username="agentuser", password="123456"))

    # 创建任务
    task = agent_task_crud.create(db, user.id, AgentTaskCreate(
        task_input="帮我总结知识库中的产品文档",
        title="产品文档总结",
    ), task_id="agent_task_test_001")
    assert task.id is not None
    assert task.status == AgentTaskStatus.PENDING.value
    print(f"  ✓ 创建Agent任务: task_id={task.task_id}, status={task.status}")

    # 状态流转
    agent_task_crud.update_status(db, task.task_id, AgentTaskStatus.PLANNING.value)
    print(f"  ✓ 状态 → planning")

    # 写入规划
    plan = [
        {"step": 1, "tool": "kb_search", "input": "产品文档", "description": "检索产品相关文档"},
        {"step": 2, "tool": "doc_summary", "input": "", "description": "生成摘要"},
    ]
    agent_task_crud.update_plan(db, task.task_id, plan)
    t = agent_task_crud.get_by_task_id(db, task.task_id)
    assert len(t.plan) == 2
    print(f"  ✓ 写入规划: {len(t.plan)} 个子任务")

    # 追加执行日志
    agent_task_crud.append_execution_log(db, task.task_id, {
        "step": 1, "tool": "kb_search", "status": "success", "output": "找到10篇文档"
    })
    agent_task_crud.append_execution_log(db, task.task_id, {
        "step": 2, "tool": "doc_summary", "status": "success", "output": "摘要内容..."
    })
    t = agent_task_crud.get_by_task_id(db, task.task_id)
    assert t.total_steps == 2
    print(f"  ✓ 执行日志: {t.total_steps} 步")

    # 反思日志
    agent_task_crud.append_reflection_log(db, task.task_id, {
        "retry": 1, "issue": "摘要不够详细", "strategy": "增加细节"
    })
    t = agent_task_crud.get_by_task_id(db, task.task_id)
    assert t.retry_count == 1
    print(f"  ✓ 反思日志: 重试 {t.retry_count} 次")

    # 设置结果
    agent_task_crud.set_result(db, task.task_id, "最终总结结果...", duration_ms=5000, tokens_used=1200)
    t = agent_task_crud.get_by_task_id(db, task.task_id)
    assert t.status == AgentTaskStatus.SUCCESS.value
    assert t.duration_ms == 5000
    print(f"  ✓ 任务完成: status={t.status}, 耗时={t.duration_ms}ms, tokens={t.tokens_used}")

    # 列表查询
    tasks, total = agent_task_crud.get_list_by_user(db, user.id)
    assert total == 1
    print(f"  ✓ 用户任务列表: {total} 个")

    db.close()
    print("  ✅ Agent 任务 CRUD 全部通过")


def test_6_audit_log():
    """测试审计日志"""
    print("\n" + "=" * 60)
    print("【测试6】审计日志 CRUD")
    print("=" * 60)

    from db.crud import user_crud, audit_log_crud
    from db.schemas import UserCreate
    from db.session import SyncSessionLocal
    from config.constants import AuditAction, AuditResult

    db = SyncSessionLocal()

    user = user_crud.create(db, UserCreate(username="audituser", password="123456"))

    # 记录多种审计日志
    audit_log_crud.create(
        db, user_id=user.id, action=AuditAction.LOGIN.value,
        ip_address="192.168.1.1", result=AuditResult.SUCCESS.value,
        details={"method": "password"},
    )
    audit_log_crud.create(
        db, user_id=user.id, action=AuditAction.KB_CREATE.value,
        resource_type="kb", resource_id="1",
        result=AuditResult.SUCCESS.value,
    )
    audit_log_crud.create(
        db, user_id=user.id, action=AuditAction.DOC_UPLOAD.value,
        resource_type="doc", resource_id="1",
        result=AuditResult.SUCCESS.value,
    )
    audit_log_crud.create(
        db, user_id=user.id, action=AuditAction.CHAT_QUESTION.value,
        result=AuditResult.SUCCESS.value,
        details={"query": "测试问题"},
    )
    audit_log_crud.create(
        db, user_id=None, action=AuditAction.LOGIN.value,
        result=AuditResult.FAILED.value,
        error_message="密码错误",
    )
    print(f"  ✓ 写入 5 条审计日志（登录/创建知识库/上传文档/问答/登录失败）")

    # 查询
    logs, total = audit_log_crud.query(db, user_id=user.id)
    assert total == 4
    print(f"  ✓ 用户审计日志: {total} 条")

    logs2, total2 = audit_log_crud.query(db, action=AuditAction.LOGIN.value)
    assert total2 == 2  # 1 成功 + 1 失败
    print(f"  ✓ 按操作类型筛选(login): {total2} 条")

    logs3, total3 = audit_log_crud.query(db, result=AuditResult.FAILED.value)
    assert total3 == 1
    print(f"  ✓ 按结果筛选(failed): {total3} 条")

    # 只追加，不修改不删除（模型中没有 update/delete 方法就是最好的验证）
    assert not hasattr(audit_log_crud, "update"), "审计日志不应有 update 方法"
    assert not hasattr(audit_log_crud, "delete"), "审计日志不应有 delete 方法"
    print(f"  ✓ 审计日志只追加，不修改不删除（无 update/delete 方法）")

    db.close()
    print("  ✅ 审计日志 CRUD 全部通过")


def main():
    print("\n" + "🚀" * 10 + " 步骤2 数据库层测试开始 " + "🚀" * 10)

    # 初始化测试数据库
    setup_test_db()
    print("  ✓ 测试数据库初始化完成（SQLite 内存库）")

    tests = [
        test_1_user_crud,
        test_2_kb_and_permission,
        test_3_document_crud,
        test_4_conversation_message,
        test_5_agent_task,
        test_6_audit_log,
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
        print("🎉 全部测试通过！步骤2 数据库层正常。")
        print()
        print("📊 数据表总览:")
        print("  1. users                    用户表")
        print("  2. knowledge_bases          知识库表")
        print("  3. knowledge_base_users     知识库-用户授权表（多对多）")
        print("  4. documents                文档元数据表")
        print("  5. document_versions        文档版本表")
        print("  6. conversations            会话表")
        print("  7. messages                 消息表")
        print("  8. agent_tasks              Agent任务表")
        print("  9. audit_logs               审计日志表")
        print()
        print("✅ 三者分离存储验证通过:")
        print("   PostgreSQL = 业务元数据")
        print("   向量库     = embedding 向量")
        print("   文件系统   = 原始文档二进制")
    else:
        print(f"⚠️  有 {failed} 项测试失败。")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
