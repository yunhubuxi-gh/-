"""
Pydantic Schema（DTO）定义

所有 API 请求/响应的数据结构都在此处定义，用于：
- 请求参数校验（入参 DTO）
- 响应数据序列化（出参 DTO）
- 自动生成 OpenAPI 文档

命名约定：
- *Create: 创建请求
- *Update: 更新请求
- *Response: 响应 DTO
- *Query: 查询参数
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator

from config.constants import (
    UserRole, UserStatus,
    KBStatus, KBUserRole,
    DocumentStatus, DocumentType,
    ConversationType, MessageRole,
    AgentTaskStatus, AuditAction, AuditResult,
)


# ============================================================
# 基础响应
# ============================================================

class BaseResponse(BaseModel):
    """基础响应字段（所有响应 DTO 都包含这些）"""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ============================================================
# 用户相关
# ============================================================

class UserCreate(BaseModel):
    """用户注册/创建"""
    username: str = Field(..., min_length=3, max_length=64, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码")
    email: Optional[str] = Field(None, max_length=128, description="邮箱")
    nickname: Optional[str] = Field(None, max_length=64, description="昵称")
    role: str = Field(default=UserRole.NORMAL.value, description="角色")

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError("用户名只能包含字母、数字和下划线")
        return v


class UserLogin(BaseModel):
    """用户登录"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class UserUpdate(BaseModel):
    """用户信息更新"""
    nickname: Optional[str] = Field(None, max_length=64)
    email: Optional[str] = Field(None, max_length=128)
    avatar: Optional[str] = Field(None, max_length=512)
    status: Optional[str] = None
    role: Optional[str] = None


class PasswordChange(BaseModel):
    """修改密码"""
    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., min_length=6, max_length=128, description="新密码")


class UserResponse(BaseResponse):
    """用户信息响应（不含密码哈希）"""
    username: str
    email: Optional[str]
    nickname: Optional[str]
    avatar: Optional[str]
    role: str
    status: str
    login_count: int
    last_login_at: Optional[datetime]


class UserLoginResponse(BaseModel):
    """登录响应（令牌 + 用户信息）"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


# ============================================================
# 知识库相关
# ============================================================

class KBCreate(BaseModel):
    """创建知识库"""
    name: str = Field(..., min_length=1, max_length=128, description="知识库名称")
    description: Optional[str] = Field(None, max_length=512, description="描述")
    icon: Optional[str] = Field(None, max_length=512, description="图标")


class KBUpdate(BaseModel):
    """更新知识库"""
    name: Optional[str] = Field(None, max_length=128)
    description: Optional[str] = Field(None, max_length=512)
    icon: Optional[str] = Field(None, max_length=512)
    status: Optional[str] = None


class KBResponse(BaseResponse):
    """知识库响应"""
    name: str
    description: Optional[str]
    icon: Optional[str]
    owner_id: int
    status: str
    doc_count: int
    chunk_count: int
    user_role: Optional[str] = Field(None, description="当前用户在知识库的角色")


class KBMemberAdd(BaseModel):
    """添加知识库成员"""
    user_id: int = Field(..., description="用户ID")
    role: str = Field(default=KBUserRole.READ.value, description="权限角色")


class KBMemberUpdate(BaseModel):
    """更新成员权限"""
    role: str = Field(..., description="新的权限角色")


class KBMemberResponse(BaseResponse):
    """知识库成员响应"""
    knowledge_base_id: int
    user_id: int
    role: str
    user: Optional[UserResponse] = None


# ============================================================
# 文档相关
# ============================================================

class DocumentUploadResponse(BaseModel):
    """文档上传响应（异步处理，返回任务ID）"""
    document_id: int
    title: str
    file_name: str
    file_size: int
    status: str
    task_id: str = Field(..., description="异步处理任务ID")


class DocumentUpdate(BaseModel):
    """文档元信息更新"""
    title: Optional[str] = Field(None, max_length=256)


class DocumentResponse(BaseResponse):
    """文档元数据响应"""
    title: str
    doc_type: str
    knowledge_base_id: int
    uploader_id: Optional[int]
    file_name: str
    file_size: int
    file_hash: Optional[str]
    status: str
    error_message: Optional[str]
    page_count: int
    char_count: int
    chunk_count: int
    current_version: int
    language: Optional[str]


class DocumentQuery(BaseModel):
    """文档查询参数"""
    knowledge_base_id: int
    keyword: Optional[str] = None
    status: Optional[str] = None
    doc_type: Optional[str] = None
    page: int = 1
    page_size: int = 20


# ============================================================
# 会话与消息相关
# ============================================================

class ConversationCreate(BaseModel):
    """创建会话"""
    title: Optional[str] = Field(None, max_length=256, description="会话标题")
    knowledge_base_id: Optional[int] = Field(None, description="关联知识库ID")
    type: str = Field(default=ConversationType.CHAT.value, description="会话类型")


class ConversationUpdate(BaseModel):
    """更新会话"""
    title: Optional[str] = Field(None, max_length=256)


class ConversationResponse(BaseResponse):
    """会话响应"""
    title: Optional[str]
    user_id: int
    knowledge_base_id: Optional[int]
    type: str
    message_count: int
    last_message_at: Optional[datetime]


class MessageResponse(BaseResponse):
    """消息响应"""
    conversation_id: int
    role: str
    content: str
    citations: Optional[List[Dict[str, Any]]] = None
    meta_info: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    """问答请求"""
    conversation_id: Optional[int] = Field(None, description="会话ID，新会话为空")
    knowledge_base_id: int = Field(..., description="知识库ID")
    query: str = Field(..., min_length=1, description="用户问题")
    stream: bool = Field(default=False, description="是否流式输出")


# ============================================================
# Agent 任务相关
# ============================================================

class AgentTaskCreate(BaseModel):
    """创建 Agent 任务"""
    conversation_id: Optional[int] = None
    knowledge_base_id: Optional[int] = None
    task_input: str = Field(..., min_length=1, description="任务描述")
    title: Optional[str] = Field(None, max_length=256)


class AgentTaskResponse(BaseResponse):
    """Agent 任务响应"""
    task_id: str
    user_id: int
    conversation_id: Optional[int]
    knowledge_base_id: Optional[int]
    title: Optional[str]
    task_input: str
    status: str
    result: Optional[str]
    result_data: Optional[Dict[str, Any]] = None
    retry_count: int
    total_steps: int
    duration_ms: int
    error_message: Optional[str]


class AgentTaskDetailResponse(AgentTaskResponse):
    """Agent 任务详情（含执行日志与规划）"""
    plan: Optional[List[Dict[str, Any]]] = None
    execution_log: Optional[List[Dict[str, Any]]] = None
    reflection_log: Optional[List[Dict[str, Any]]] = None


# ============================================================
# 审计日志相关
# ============================================================

class AuditLogResponse(BaseResponse):
    """审计日志响应"""
    user_id: Optional[int]
    action: str
    result: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    ip_address: Optional[str]
    request_method: Optional[str]
    request_path: Optional[str]
    details: Optional[Dict[str, Any]] = None
    error_message: Optional[str]


class AuditLogQuery(BaseModel):
    """审计日志查询参数"""
    user_id: Optional[int] = None
    action: Optional[str] = None
    result: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    page: int = 1
    page_size: int = 20
