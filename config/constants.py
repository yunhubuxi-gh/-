"""
常量与枚举定义
所有魔法数字、魔法字符串都集中在此处定义，业务代码禁止直接写字面量。
"""
from __future__ import annotations

from enum import Enum


# ============================================================
# 用户相关
# ============================================================

class UserRole(str, Enum):
    """用户角色"""
    ADMIN = "admin"           # 管理员（全部权限）
    NORMAL = "normal"         # 普通用户
    GUEST = "guest"           # 访客（只读）


class UserStatus(str, Enum):
    """用户状态"""
    ACTIVE = "active"         # 正常
    DISABLED = "disabled"     # 禁用
    LOCKED = "locked"         # 锁定（多次登录失败）


# ============================================================
# 知识库相关
# ============================================================

class KBUserRole(str, Enum):
    """知识库用户权限级别"""
    OWNER = "owner"           # 所有者（全部权限）
    ADMIN = "admin"           # 管理员（可管理成员、文档）
    WRITE = "write"           # 读写（可上传/删除文档）
    READ = "read"             # 只读


class KBStatus(str, Enum):
    """知识库状态"""
    ACTIVE = "active"
    ARCHIVED = "archived"     # 归档


# ============================================================
# 文档相关
# ============================================================

class DocumentStatus(str, Enum):
    """文档处理状态"""
    UPLOADED = "uploaded"       # 已上传，待解析
    PARSING = "parsing"         # 解析文件
    EXTRACTING_IMAGES = "extracting_images"   # 提取图片（PDF 内嵌图）
    OCR = "ocr"                 # OCR 识别图片文字
    PARSED = "parsed"           # 解析完成，待向量化
    EMBEDDING = "embedding"     # 文本分块 & 文本向量化
    IMAGE_EMBEDDING = "image_embedding"       # 图片多模态 Embedding 向量化
    READY = "ready"             # 就绪（可检索）
    FAILED = "failed"           # 处理失败
    ARCHIVED = "archived"       # 已归档


class DocumentType(str, Enum):
    """文档类型"""
    PDF = "pdf"
    DOCX = "docx"
    MARKDOWN = "md"
    TXT = "txt"
    IMAGE = "image"             # 图片（png/jpg，走多模态 + OCR 双通道）


# 支持的文件扩展名 -> 文档类型映射
SUPPORTED_EXTENSIONS = {
    ".pdf": DocumentType.PDF,
    ".docx": DocumentType.DOCX,
    ".md": DocumentType.MARKDOWN,
    ".markdown": DocumentType.MARKDOWN,
    ".txt": DocumentType.TXT,
    ".png": DocumentType.IMAGE,
    ".jpg": DocumentType.IMAGE,
    ".jpeg": DocumentType.IMAGE,
}


# ============================================================
# 会话相关
# ============================================================

class ConversationType(str, Enum):
    """会话类型"""
    CHAT = "chat"             # 普通 RAG 问答
    AGENT = "agent"           # Agent 任务模式


class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


# ============================================================
# Agent 任务相关
# ============================================================

class AgentTaskStatus(str, Enum):
    """Agent 任务状态"""
    PENDING = "pending"         # 等待执行
    PLANNING = "planning"       # 规划中
    EXECUTING = "executing"     # 执行中
    REFLECTING = "reflecting"   # 反思中
    SUCCESS = "success"         # 成功
    FAILED = "failed"           # 失败
    CANCELLED = "cancelled"     # 已取消


class ToolCategory(str, Enum):
    """工具分类"""
    INTERNAL_RAG = "internal_rag"   # 内部 RAG 检索工具
    EXTERNAL_BIZ = "external_biz"   # 外部业务工具


# ============================================================
# 审计日志相关
# ============================================================

class AuditAction(str, Enum):
    """审计操作类型"""
    # 认证相关
    LOGIN = "login"
    LOGOUT = "logout"
    REGISTER = "register"
    TOKEN_REFRESH = "token_refresh"

    # 知识库相关
    KB_CREATE = "kb_create"
    KB_UPDATE = "kb_update"
    KB_DELETE = "kb_delete"
    KB_MEMBER_ADD = "kb_member_add"
    KB_MEMBER_REMOVE = "kb_member_remove"
    KB_MEMBER_UPDATE = "kb_member_update"

    # 文档相关
    DOC_UPLOAD = "doc_upload"
    DOC_DELETE = "doc_delete"
    DOC_UPDATE = "doc_update"
    DOC_REBUILD = "doc_rebuild"      # 重建索引

    # 问答相关
    CHAT_QUESTION = "chat_question"

    # Agent 相关
    AGENT_TASK_CREATE = "agent_task_create"
    AGENT_TASK_COMPLETE = "agent_task_complete"

    # 管理相关
    USER_CREATE = "user_create"
    USER_UPDATE = "user_update"
    USER_DELETE = "user_delete"


class AuditResult(str, Enum):
    """审计结果"""
    SUCCESS = "success"
    FAILED = "failed"
    PERMISSION_DENIED = "permission_denied"


# ============================================================
# 向量库相关
# ============================================================

class VectorStoreType(str, Enum):
    """向量库类型"""
    CHROMA = "chroma"
    MILVUS = "milvus"


# ============================================================
# 异步任务相关
# ============================================================

class TaskType(str, Enum):
    """异步任务类型"""
    DOC_PARSE = "doc_parse"               # 文档解析
    DOC_EMBED = "doc_embed"               # 文档向量化
    DOC_FULL_PROCESS = "doc_full_process" # 文档完整处理（解析+向量化）
    KB_REINDEX = "kb_reindex"             # 知识库重建索引
    EXPORT_TASK = "export_task"           # 导出任务


# ============================================================
# 分页默认值
# ============================================================

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200


# ============================================================
# 文本处理相关
# ============================================================

# 中文停用词（基础版，用于 BM25 等场景）
DEFAULT_STOPWORDS = {
    "的", "了", "和", "是", "就", "都", "而", "及", "与", "着",
    "或", "一个", "没有", "我们", "你们", "他们", "她们", "它们",
    "这", "那", "这个", "那个", "这些", "那些", "这样", "那样",
    "也", "还", "又", "再", "就", "才", "只", "很", "更", "最",
    "在", "有", "不", "人", "上", "中", "下", "为", "以", "于",
    "对", "从", "到", "被", "把", "让", "给", "向", "由", "等",
    "啊", "呢", "吧", "吗", "哦", "嗯", "哈", "呀", "啦",
}
