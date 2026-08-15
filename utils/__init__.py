"""
utils 通用工具层

所有公共工具函数、客户端封装、基础设施都集中在此层。
业务层、AI 能力层、API 层统一通过本层使用公共能力，杜绝工具函数散落。

模块说明：
- logger: 统一日志获取入口
- config_loader: 配置加载封装
- error_codes: 统一错误码体系
- exceptions: 自定义异常类
- response: 统一响应封装
- llm_client: 大模型客户端（OpenAI 兼容）
- embedding_client: 嵌入模型客户端
- ocr_engine: OCR 引擎封装
- security: 安全工具（JWT / 密码哈希）
- file_utils: 文件处理工具
- text_utils: 文本处理工具
- permission: 权限校验工具
- async_task: 异步任务封装
"""
from utils.logger import get_logger, get_audit_logger
from utils.exceptions import (
    AppException,
    AuthException,
    PermissionException,
    ResourceNotFoundException,
    ValidationException,
    RAGException,
    AgentException,
)
from utils.response import success_response, fail_response, error_response, PageResult

__all__ = [
    "get_logger",
    "get_audit_logger",
    # exceptions
    "AppException",
    "AuthException",
    "PermissionException",
    "ResourceNotFoundException",
    "ValidationException",
    "RAGException",
    "AgentException",
    # response
    "success_response",
    "fail_response",
    "error_response",
    "PageResult",
]
