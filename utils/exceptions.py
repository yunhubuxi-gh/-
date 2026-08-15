"""
自定义异常类体系
所有业务异常都继承自 AppException，携带错误码与消息。
全局异常处理器根据异常类型返回对应 HTTP 状态码。
"""
from __future__ import annotations

from utils.error_codes import ErrorCode, UNKNOWN_ERROR


class AppException(Exception):
    """
    应用基异常

    Attributes:
        error_code: 错误码对象
        message:  错误消息
        details:  详细信息（调试用）
    """

    def __init__(
        self,
        error_code: ErrorCode = UNKNOWN_ERROR,
        message: str | None = None,
        details: dict | None = None,
    ):
        self.error_code = error_code
        self.message = message or error_code.message
        self.details = details or {}
        super().__init__(self.message)

    @property
    def code(self) -> int:
        return self.error_code.code

    @property
    def http_status(self) -> int:
        return self.error_code.http_status

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class AuthException(AppException):
    """认证异常（未登录、token 无效等）"""
    pass


class PermissionException(AppException):
    """权限不足异常"""
    pass


class ResourceNotFoundException(AppException):
    """资源不存在异常"""
    pass


class ValidationException(AppException):
    """参数校验异常"""
    pass


class RAGException(AppException):
    """RAG 模块异常"""
    pass


class AgentException(AppException):
    """Agent 模块异常"""
    pass


class FileOperationException(AppException):
    """文件操作异常"""
    pass
