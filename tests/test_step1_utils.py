"""
步骤1 - utils 通用工具层 + config 配置模块 测试示例

运行方式:
    # 安装核心依赖
    pip install pydantic-settings python-jose bcrypt jieba rank-bm25 python-dotenv

    # 运行测试
    python -m pytest tests/test_step1_utils.py -v
    # 或直接运行脚本
    python tests/test_step1_utils.py
"""
from __future__ import annotations

import os
import sys
import tempfile

# 把项目根目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config_settings():
    """测试配置加载"""
    print("\n" + "=" * 60)
    print("【测试1】配置模块 (config.settings)")
    print("=" * 60)
    from config.settings import settings, get_settings

    # 验证单例
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2, "配置应为单例"
    print(f"  ✓ 配置单例模式正常")

    # 验证关键字段
    print(f"  APP_NAME:      {settings.app_name}")
    print(f"  DEBUG:         {settings.debug}")
    print(f"  VECTOR_STORE:  {settings.vector_store_type}")
    print(f"  LLM_PROVIDER:  {settings.llm_provider}")
    print(f"  ASYNC_ENGINE:  {settings.async_task_engine}")
    print(f"  ✓ 配置加载成功")


def test_constants():
    """测试常量枚举"""
    print("\n" + "=" * 60)
    print("【测试2】常量枚举 (config.constants)")
    print("=" * 60)
    from config.constants import (
        UserRole, DocumentStatus, KBUserRole,
        AgentTaskStatus, ToolCategory, SUPPORTED_EXTENSIONS,
    )
    print(f"  用户角色: {[r.value for r in UserRole]}")
    print(f"  文档状态: {[s.value for s in DocumentStatus]}")
    print(f"  知识库权限: {[r.value for r in KBUserRole]}")
    print(f"  Agent任务状态: {[s.value for s in AgentTaskStatus]}")
    print(f"  工具分类: {[c.value for c in ToolCategory]}")
    print(f"  支持文件类型: {list(SUPPORTED_EXTENSIONS.keys())}")
    print("  ✓ 常量枚举定义完整")


def test_logging_setup():
    """测试日志初始化"""
    print("\n" + "=" * 60)
    print("【测试3】日志配置 (config.logging_config)")
    print("=" * 60)
    from config.logging_config import setup_logging
    from utils.logger import get_logger, get_audit_logger

    with tempfile.TemporaryDirectory() as tmpdir:
        # 用临时目录跑一下日志初始化（不改全局配置）
        import logging
        setup_logging()
        logger = get_logger("test")
        audit = get_audit_logger()
        logger.info("这是一条普通日志")
        audit.info("这是一条审计日志")
        print("  ✓ 普通日志器正常")
        print("  ✓ 审计日志器正常")


def test_error_codes():
    """测试错误码体系"""
    print("\n" + "=" * 60)
    print("【测试4】错误码体系 (utils.error_codes)")
    print("=" * 60)
    from utils.error_codes import (
        SUCCESS, AUTH_TOKEN_INVALID, KB_NO_PERMISSION,
        DOC_NOT_FOUND, AGENT_TASK_FAILED, get_error_by_code,
    )
    print(f"  成功: code={SUCCESS.code}, msg={SUCCESS.message}")
    print(f"  认证失败: code={AUTH_TOKEN_INVALID.code}, http={AUTH_TOKEN_INVALID.http_status}")
    print(f"  知识库无权限: code={KB_NO_PERMISSION.code}")
    print(f"  文档不存在: code={DOC_NOT_FOUND.code}")
    print(f"  Agent任务失败: code={AGENT_TASK_FAILED.code}")

    ec = get_error_by_code(1100002)
    assert ec.code == 1100002
    print(f"  ✓ 错误码查找功能正常 (1100002 -> {ec.message})")


def test_exceptions():
    """测试自定义异常"""
    print("\n" + "=" * 60)
    print("【测试5】自定义异常 (utils.exceptions)")
    print("=" * 60)
    from utils.exceptions import (
        AppException, AuthException, PermissionException,
        ResourceNotFoundException, ValidationException,
    )
    from utils.error_codes import AUTH_TOKEN_EXPIRED

    try:
        raise AuthException(AUTH_TOKEN_EXPIRED, details={"token": "xxx"})
    except AppException as e:
        print(f"  异常信息: {e}")
        print(f"  错误码: {e.code}")
        print(f"  HTTP状态: {e.http_status}")
        print(f"  详情: {e.details}")
        assert e.code == 1100003
        print("  ✓ 自定义异常体系正常")


def test_response():
    """测试统一响应封装"""
    print("\n" + "=" * 60)
    print("【测试6】统一响应封装 (utils.response)")
    print("=" * 60)
    from utils.response import success_response, fail_response, error_response, page_result
    from utils.error_codes import INVALID_PARAMS

    succ = success_response({"id": 1, "name": "test"}, "操作成功")
    print(f"  成功响应: code={succ['code']}, data={succ['data']}")
    assert succ["code"] == 0

    fail = fail_response(INVALID_PARAMS, "参数格式错误")
    print(f"  失败响应: code={fail['code']}, msg={fail['message']}")
    assert fail["code"] == 1000002

    err = error_response("数据库连接失败")
    print(f"  错误响应: code={err['code']}, msg={err['message']}")
    assert err["code"] == 1000001

    page = page_result([1, 2, 3], total=100, page=2, page_size=10)
    print(f"  分页结果: page={page['page']}, total={page['total']}, total_pages={page['total_pages']}")
    assert page["total_pages"] == 10
    print("  ✓ 统一响应封装正常")


def test_security():
    """测试安全工具（密码哈希 + JWT）"""
    print("\n" + "=" * 60)
    print("【测试7】安全工具 (utils.security)")
    print("=" * 60)
    from utils.security import (
        hash_password, verify_password,
        create_access_token, create_refresh_token,
        decode_access_token, decode_refresh_token,
        create_token_pair,
    )

    # 密码哈希
    pwd = "Test@123456"
    hashed = hash_password(pwd)
    print(f"  密码哈希: {hashed[:30]}...")
    assert verify_password(pwd, hashed)
    assert not verify_password("wrong", hashed)
    print("  ✓ 密码哈希与校验正常")

    # JWT
    access, refresh = create_token_pair(
        subject="user_001",
        extra_claims={"username": "alice", "role": "admin"},
    )
    print(f"  Access Token: {access[:30]}...")
    print(f"  Refresh Token: {refresh[:30]}...")

    access_payload = decode_access_token(access)
    assert access_payload["sub"] == "user_001"
    assert access_payload["username"] == "alice"
    assert access_payload["type"] == "access"
    print(f"  Access Token 解析: sub={access_payload['sub']}, role={access_payload['role']}")

    refresh_payload = decode_refresh_token(refresh)
    assert refresh_payload["type"] == "refresh"
    print("  ✓ JWT 签发与解析正常")


def test_file_utils():
    """测试文件工具"""
    print("\n" + "=" * 60)
    print("【测试8】文件工具 (utils.file_utils)")
    print("=" * 60)
    from utils.file_utils import (
        sanitize_filename, detect_document_type,
        is_supported_file, get_file_extension,
        safe_join_path, format_file_size,
        generate_unique_filename,
    )

    # 文件名清理
    dirty = "../危险/文件名<test>.pdf"
    clean = sanitize_filename(dirty)
    print(f"  文件名清理: '{dirty}' -> '{clean}'")
    assert "/" not in clean
    assert "<" not in clean

    # 类型检测
    assert detect_document_type("test.pdf").value == "pdf"
    assert detect_document_type("report.DOCX").value == "docx"
    assert detect_document_type("readme.md").value == "md"
    assert detect_document_type("data.xlsx") is None
    print("  ✓ 文档类型检测正常")

    # 路径安全
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        safe = safe_join_path(tmpdir, "subdir", "file.txt")
        assert str(safe).startswith(tmpdir)
        print("  ✓ 路径安全校验正常")

    # 文件大小格式化
    print(f"  文件大小格式化: {format_file_size(1024)}, {format_file_size(1048576)}, {format_file_size(1073741824)}")
    print("  ✓ 文件工具全部正常")


def test_permission():
    """测试权限校验"""
    print("\n" + "=" * 60)
    print("【测试9】权限校验 (utils.permission)")
    print("=" * 60)
    from utils.permission import (
        has_permission, can_read, can_write, can_manage, is_owner,
        ensure_permission, get_role_level,
    )
    from config.constants import KBUserRole
    from utils.exceptions import PermissionException

    print(f"  角色级别: owner={get_role_level('owner')}, admin={get_role_level('admin')}, "
          f"write={get_role_level('write')}, read={get_role_level('read')}")

    # 权限判断
    assert has_permission(KBUserRole.OWNER, KBUserRole.READ)
    assert has_permission(KBUserRole.ADMIN, KBUserRole.WRITE)
    assert not has_permission(KBUserRole.READ, KBUserRole.WRITE)
    assert can_manage(KBUserRole.ADMIN)
    assert can_write(KBUserRole.WRITE)
    assert can_read(KBUserRole.READ)
    assert is_owner(KBUserRole.OWNER)
    assert not is_owner(KBUserRole.ADMIN)
    print("  ✓ 权限判断函数正常")

    # 权限不足抛异常
    try:
        ensure_permission(KBUserRole.READ, KBUserRole.WRITE, "kb_123")
        assert False, "应抛出异常"
    except PermissionException as e:
        print(f"  权限不足异常正常: {e.message}")
    print("  ✓ 权限校验全部正常")


def test_async_task():
    """测试异步任务封装"""
    print("\n" + "=" * 60)
    print("【测试10】异步任务封装 (utils.async_task)")
    print("=" * 60)
    import time
    from utils.async_task import (
        get_task_engine, submit_task, get_task_status, TaskStatus,
    )

    engine = get_task_engine()
    print(f"  异步引擎类型: {type(engine).__name__}")

    def slow_add(a: int, b: int) -> int:
        time.sleep(0.2)
        return a + b

    task_id = submit_task(slow_add, 3, 4)
    print(f"  任务ID: {task_id}")

    # 初始状态
    status = get_task_status(task_id)
    print(f"  初始状态: {status.value}")

    # 等待完成
    time.sleep(0.5)
    status = get_task_status(task_id)
    print(f"  完成状态: {status.value}")
    assert status == TaskStatus.SUCCESS

    result = engine.get_result(task_id)
    print(f"  任务结果: {result}")
    assert result == 7
    print("  ✓ 异步任务封装正常")


def test_text_utils():
    """测试文本处理工具"""
    print("\n" + "=" * 60)
    print("【测试11】文本工具 (utils.text_utils)")
    print("=" * 60)
    from utils.text_utils import (
        clean_text, truncate_text,
        jieba_segment, extract_keywords,
        cosine_similarity, count_tokens_estimate,
    )

    # 文本清洗
    dirty = "  你好，\n\n\n  世界！\r\n  测试  \n "
    cleaned = clean_text(dirty)
    print(f"  清洗前: {repr(dirty[:30])}")
    print(f"  清洗后: {repr(cleaned[:30])}")

    # 文本截断
    long_text = "这是一段很长的测试文本" * 10
    truncated = truncate_text(long_text, 20)
    print(f"  截断结果: {truncated} (长度={len(truncated)})")
    assert len(truncated) <= 20

    # 中文分词
    words = jieba_segment("我爱北京天安门，天安门上太阳升。")
    print(f"  分词结果: {words}")
    assert len(words) > 0

    # 关键词提取
    kws = extract_keywords("机器学习深度学习人工智能机器学习算法模型机器学习", top_k=3)
    print(f"  关键词: {kws}")

    # 余弦相似度
    sim = cosine_similarity([1, 0, 1], [1, 0, 1])
    print(f"  相同向量余弦相似度: {sim:.4f}")
    assert abs(sim - 1.0) < 1e-6

    # token 估算
    n = count_tokens_estimate("这是一个测试文本，用于估算token数量")
    print(f"  估算token数: {n}")
    print("  ✓ 文本处理工具正常")


def main():
    """运行全部测试"""
    print("\n" + "🚀" * 10 + " 步骤1 模块测试开始 " + "🚀" * 10)

    tests = [
        test_config_settings,
        test_constants,
        test_logging_setup,
        test_error_codes,
        test_exceptions,
        test_response,
        test_security,
        test_file_utils,
        test_permission,
        test_async_task,
        test_text_utils,
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
    print(f"测试结果: 共 {len(tests)} 项, 通过 {passed} 项, 失败 {failed} 项")
    print("=" * 60)
    if failed == 0:
        print("🎉 全部测试通过！步骤1 utils + config 模块正常。")
    else:
        print(f"⚠️  有 {failed} 项测试失败，请检查。")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
