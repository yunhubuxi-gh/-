"""
统一错误码定义
格式：AABBCCC
- AA: 模块号 (10=通用, 11=认证, 12=知识库, 13=文档, 14=问答, 15=Agent, 16=权限)
- BB: 子模块/分类
- CCC: 具体错误编号

与 HTTP 状态码映射，便于前端统一处理。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ErrorCode:
    """错误码数据类"""
    code: int
    message: str
    http_status: int = 400


# ========== 通用错误 10xxxxx ==========
SUCCESS = ErrorCode(0, "成功", 200)
UNKNOWN_ERROR = ErrorCode(1000001, "系统内部错误", 500)
INVALID_PARAMS = ErrorCode(1000002, "请求参数错误", 400)
RESOURCE_NOT_FOUND = ErrorCode(1000003, "资源不存在", 404)
RESOURCE_ALREADY_EXISTS = ErrorCode(1000004, "资源已存在", 409)
OPERATION_NOT_ALLOWED = ErrorCode(1000005, "操作不允许", 403)
RATE_LIMIT_EXCEEDED = ErrorCode(1000006, "请求过于频繁", 429)
SERVICE_UNAVAILABLE = ErrorCode(1000007, "服务暂不可用", 503)

# ========== 认证错误 11xxxxx ==========
AUTH_TOKEN_MISSING = ErrorCode(1100001, "缺少认证令牌", 401)
AUTH_TOKEN_INVALID = ErrorCode(1100002, "认证令牌无效", 401)
AUTH_TOKEN_EXPIRED = ErrorCode(1100003, "认证令牌已过期", 401)
AUTH_CREDENTIALS_ERROR = ErrorCode(1100004, "用户名或密码错误", 401)
AUTH_USER_NOT_FOUND = ErrorCode(1100005, "用户不存在", 401)
AUTH_USER_DISABLED = ErrorCode(1100006, "用户已被禁用", 403)
AUTH_REFRESH_TOKEN_INVALID = ErrorCode(1100007, "刷新令牌无效", 401)

# ========== 知识库错误 12xxxxx ==========
KB_NOT_FOUND = ErrorCode(1200001, "知识库不存在", 404)
KB_NAME_DUPLICATE = ErrorCode(1200002, "知识库名称重复", 409)
KB_NO_PERMISSION = ErrorCode(1200003, "无该知识库访问权限", 403)
KB_CREATE_FAILED = ErrorCode(1200004, "知识库创建失败", 500)

# ========== 文档错误 13xxxxx ==========
DOC_NOT_FOUND = ErrorCode(1300001, "文档不存在", 404)
DOC_UPLOAD_FAILED = ErrorCode(1300002, "文档上传失败", 500)
DOC_UNSUPPORTED_TYPE = ErrorCode(1300003, "不支持的文档类型", 400)
DOC_FILE_TOO_LARGE = ErrorCode(1300004, "文件过大", 413)
DOC_PARSE_FAILED = ErrorCode(1300005, "文档解析失败", 500)
DOC_EMBEDDING_FAILED = ErrorCode(1300006, "文档向量化失败", 500)
DOC_PROCESSING = ErrorCode(1300007, "文档正在处理中，请稍后", 202)

# ========== 问答错误 14xxxxx ==========
CHAT_EMPTY_QUERY = ErrorCode(1400001, "查询内容不能为空", 400)
CHAT_NO_RELEVANT_DOCS = ErrorCode(1400002, "未找到相关文档", 200)
CHAT_LLM_ERROR = ErrorCode(1400003, "大模型调用失败", 503)
CHAT_CONVERSATION_NOT_FOUND = ErrorCode(1400004, "会话不存在", 404)

# ========== Agent 错误 15xxxxx ==========
AGENT_TASK_FAILED = ErrorCode(1500001, "Agent 任务执行失败", 500)
AGENT_MAX_RETRY_EXCEEDED = ErrorCode(1500002, "Agent 超过最大重试次数", 500)
AGENT_TOOL_NOT_FOUND = ErrorCode(1500003, "Agent 工具不存在", 404)
AGENT_TASK_NOT_FOUND = ErrorCode(1500004, "Agent 任务不存在", 404)

# ========== 权限错误 16xxxxx ==========
PERMISSION_DENIED = ErrorCode(1600001, "权限不足", 403)
PERMISSION_INVALID_ROLE = ErrorCode(1600002, "无效的角色", 400)


# 错误码映射表，便于快速查找
ERROR_CODE_MAP: Dict[int, ErrorCode] = {
    v.code: v for k, v in globals().items() if isinstance(v, ErrorCode)
}


def get_error_by_code(code: int) -> ErrorCode:
    """根据错误码获取 ErrorCode 对象"""
    return ERROR_CODE_MAP.get(code, UNKNOWN_ERROR)
