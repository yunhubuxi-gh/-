"""
数据库 ORM 模型定义

严格遵守三者分离存储原则：
- 本文件只定义业务元数据表
- 原始文档二进制 -> 文件系统
- 向量 embedding -> 向量数据库（Chroma / Milvus）
- 绝对不在 PostgreSQL 存 embedding 数组或文档正文

表关系（ER 图）：
    users ──1:N── knowledge_bases (owner_id)
    users ──N:M── knowledge_base_users (多对多授权表)
    knowledge_bases ──1:N── documents
    documents ──1:N── document_versions
    users ──1:N── conversations
    knowledge_bases ──1:N── conversations
    conversations ──1:N── messages
    users ──1:N── agent_tasks
    conversations ──1:N── agent_tasks
    users ──1:N── audit_logs
"""
from __future__ import annotations

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime,
    ForeignKey, UniqueConstraint, Index, Float, JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import ENUM as PgEnum  # PostgreSQL 枚举

from db.base import BaseModel
from config.constants import (
    UserRole, UserStatus,
    KBStatus, KBUserRole,
    DocumentStatus, DocumentType,
    ConversationType, MessageRole,
    AgentTaskStatus, ToolCategory,
    AuditAction, AuditResult,
    ExamPaperStatus, ExamQuestionType, AnswerSheetStatus,
)


# ============================================================
# 1. 用户表
# ============================================================

class User(BaseModel):
    """
    用户表

    注意：密码只存储 bcrypt 哈希，绝对禁止明文存储。
    """
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
        Index("idx_users_role", "role"),
        Index("idx_users_status", "status"),
        {"comment": "用户表"},
    )

    username = Column(String(64), nullable=False, index=True, comment="用户名")
    email = Column(String(128), nullable=True, index=True, comment="邮箱")
    password_hash = Column(String(256), nullable=False, comment="密码哈希（bcrypt）")

    nickname = Column(String(64), nullable=True, comment="昵称")
    avatar = Column(String(512), nullable=True, comment="头像URL")

    role = Column(
        String(32),
        nullable=False,
        default=UserRole.NORMAL.value,
        comment="角色: admin/normal/guest",
    )
    status = Column(
        String(32),
        nullable=False,
        default=UserStatus.ACTIVE.value,
        comment="状态: active/disabled/locked",
    )

    login_count = Column(Integer, default=0, comment="登录次数")
    last_login_at = Column(DateTime, nullable=True, comment="最后登录时间")
    last_login_ip = Column(String(64), nullable=True, comment="最后登录IP")

    # 关系
    owned_knowledge_bases = relationship(
        "KnowledgeBase",
        back_populates="owner",
        foreign_keys="KnowledgeBase.owner_id",
        lazy="dynamic",
    )
    kb_memberships = relationship(
        "KnowledgeBaseUser",
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    conversations = relationship(
        "Conversation",
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    agent_tasks = relationship(
        "AgentTask",
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    audit_logs = relationship(
        "AuditLog",
        back_populates="user",
        lazy="dynamic",
    )


# ============================================================
# 2. 知识库表
# ============================================================

class KnowledgeBase(BaseModel):
    """
    知识库表

    每个知识库是一个独立的文档集合，拥有独立的向量集合和 BM25 索引。
    权限隔离通过 knowledge_base_users 多对多表实现。
    """
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        Index("idx_kb_owner_id", "owner_id"),
        Index("idx_kb_status", "status"),
        {"comment": "知识库表"},
    )

    name = Column(String(128), nullable=False, comment="知识库名称")
    description = Column(String(512), nullable=True, comment="知识库描述")
    icon = Column(String(512), nullable=True, comment="图标")
    tags = Column(
        JSON,
        nullable=True,
        comment="课程标签（课程库语义，字符串数组，如 [\"数据结构\",\"算法\"]）",
    )

    owner_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="所有者用户ID",
    )

    status = Column(
        String(32),
        nullable=False,
        default=KBStatus.ACTIVE.value,
        comment="状态: active/archived",
    )

    doc_count = Column(Integer, default=0, comment="文档数量")
    chunk_count = Column(Integer, default=0, comment="总块数（分块后）")
    vector_collection = Column(
        String(128),
        nullable=True,
        comment="向量库集合名称（通常为 kb_{id}）",
    )

    # 关系
    owner = relationship("User", back_populates="owned_knowledge_bases", foreign_keys=[owner_id])
    members = relationship(
        "KnowledgeBaseUser",
        back_populates="knowledge_base",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    documents = relationship(
        "Document",
        back_populates="knowledge_base",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    conversations = relationship(
        "Conversation",
        back_populates="knowledge_base",
        lazy="dynamic",
    )


# ============================================================
# 3. 知识库-用户 多对多授权表
# ============================================================

class KnowledgeBaseUser(BaseModel):
    """
    知识库-用户 授权关系表（多对多）

    实现知识库级别的权限隔离。
    权限级别：owner > admin > write > read
    """
    __tablename__ = "knowledge_base_users"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "user_id", name="uq_kbu_kb_user"),
        Index("idx_kbu_user_id", "user_id"),
        Index("idx_kbu_role", "role"),
        {"comment": "知识库用户授权表"},
    )

    knowledge_base_id = Column(
        Integer,
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        comment="知识库ID",
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="用户ID",
    )
    role = Column(
        String(32),
        nullable=False,
        default=KBUserRole.READ.value,
        comment="权限级别: owner/admin/write/read",
    )

    # 关系
    knowledge_base = relationship("KnowledgeBase", back_populates="members")
    user = relationship("User", back_populates="kb_memberships")


# ============================================================
# 4. 文档元数据表
# ============================================================

class Document(BaseModel):
    """
    文档元数据表

    ⚠️  只存元数据，不存文档正文，不存 embedding 向量。
    - 原始文档文件 -> 文件系统（file_path 字段记录路径）
    - 文档分块内容与向量 -> 向量数据库
    - BM25 索引 -> 本地索引文件

    文档正文如需查阅，通过 file_path 读取原始文件。
    """
    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_doc_kb_id", "knowledge_base_id"),
        Index("idx_doc_status", "status"),
        Index("idx_doc_doc_type", "doc_type"),
        Index("idx_doc_file_hash", "file_hash"),
        {"comment": "文档元数据表"},
    )

    title = Column(String(256), nullable=False, comment="文档标题")
    doc_type = Column(
        String(16),
        nullable=False,
        default=DocumentType.PDF.value,
        comment="文档类型: pdf/docx/md/txt",
    )

    knowledge_base_id = Column(
        Integer,
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属知识库ID",
    )

    uploader_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="上传者用户ID",
    )

    # 文件相关（不存内容，只存路径与元信息）
    file_path = Column(String(512), nullable=False, comment="文件在文件系统中的路径")
    file_name = Column(String(256), nullable=False, comment="原始文件名")
    file_size = Column(Integer, default=0, comment="文件大小（字节）")
    file_hash = Column(String(64), nullable=True, index=True, comment="文件SHA256哈希（用于去重）")

    # 处理状态
    status = Column(
        String(32),
        nullable=False,
        default=DocumentStatus.UPLOADED.value,
        comment="处理状态: uploaded/parsing/parsed/embedding/ready/failed",
    )
    error_message = Column(Text, nullable=True, comment="处理失败的错误信息")
    processing_warning = Column(
        Text,
        nullable=True,
        comment="处理过程中的警告信息（如部分图片向量化失败，文本已正常入库；不影响整体就绪）",
    )

    # 解析统计
    page_count = Column(Integer, default=0, comment="页数（PDF）")
    char_count = Column(Integer, default=0, comment="字符总数")
    chunk_count = Column(Integer, default=0, comment="分块总数")

    # 版本
    current_version = Column(Integer, default=1, comment="当前版本号")
    language = Column(String(16), nullable=True, default="zh", comment="主要语言")

    # 关系
    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    versions = relationship(
        "DocumentVersion",
        back_populates="document",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version.desc()",
    )


# ============================================================
# 5. 文档版本表
# ============================================================

class DocumentVersion(BaseModel):
    """
    文档版本表

    每次上传同名文档创建新版本，支持版本回滚。
    每个版本对应独立的分块与向量索引。
    """
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_doc_ver_doc_version"),
        Index("idx_doc_ver_doc_id", "document_id"),
        {"comment": "文档版本表"},
    )

    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        comment="文档ID",
    )
    version = Column(Integer, nullable=False, default=1, comment="版本号")

    file_path = Column(String(512), nullable=False, comment="该版本文件路径")
    file_hash = Column(String(64), nullable=True, comment="文件哈希")
    file_size = Column(Integer, default=0, comment="文件大小")

    chunk_count = Column(Integer, default=0, comment="分块数")
    char_count = Column(Integer, default=0, comment="字符数")

    change_log = Column(String(512), nullable=True, comment="版本变更说明")
    uploaded_by = Column(Integer, nullable=True, comment="上传者用户ID")

    # 关系
    document = relationship("Document", back_populates="versions")


# ============================================================
# 6. 会话表
# ============================================================

class Conversation(BaseModel):
    """
    会话表

    记录对话会话的元信息。对话内容存储在 messages 表中。
    会话类型区分普通 RAG 问答与 Agent 任务模式。
    """
    __tablename__ = "conversations"
    __table_args__ = (
        Index("idx_conv_user_id", "user_id"),
        Index("idx_conv_kb_id", "knowledge_base_id"),
        Index("idx_conv_type", "type"),
        Index("idx_conv_updated_at", "updated_at"),
        {"comment": "会话表"},
    )

    title = Column(String(256), nullable=True, comment="会话标题（AI生成或用户设置）")

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="用户ID",
    )
    knowledge_base_id = Column(
        Integer,
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联知识库ID（可以为空，Agent模式可能跨库）",
    )

    type = Column(
        String(16),
        nullable=False,
        default=ConversationType.CHAT.value,
        comment="会话类型: chat/agent",
    )

    message_count = Column(Integer, default=0, comment="消息数")
    last_message_at = Column(DateTime, nullable=True, comment="最后消息时间")

    # 关系
    user = relationship("User", back_populates="conversations")
    knowledge_base = relationship("KnowledgeBase", back_populates="conversations")
    messages = relationship(
        "Message",
        back_populates="conversation",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="Message.id.asc()",
    )
    agent_tasks = relationship(
        "AgentTask",
        back_populates="conversation",
        lazy="dynamic",
    )


# ============================================================
# 7. 消息表
# ============================================================

class Message(BaseModel):
    """
    消息表

    存储对话内容。长文本正常存储（TEXT 类型）。
    引用来源单独存 JSON 字段，不与内容混淆。
    """
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_msg_conv_id", "conversation_id"),
        Index("idx_msg_role", "role"),
        Index("idx_msg_created_at", "created_at"),
        {"comment": "消息表"},
    )

    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        comment="会话ID",
    )

    role = Column(
        String(16),
        nullable=False,
        default=MessageRole.USER.value,
        comment="角色: user/assistant/system/tool",
    )

    content = Column(Text, nullable=False, comment="消息内容")

    # 引用来源（AI 回答时附带，JSON 数组）
    citations = Column(
        JSON,
        nullable=True,
        comment="引用来源列表 [{document_id, document_name, page, score, chunk_id}]",
    )

    # 元信息（字段名不用 metadata，避免与 SQLAlchemy 保留名冲突）
    meta_info = Column(
        JSON,
        nullable=True,
        comment="消息元信息（如 token 用量、模型名、耗时等）",
    )

    # 关系
    conversation = relationship("Conversation", back_populates="messages")


# ============================================================
# 8. Agent 任务表
# ============================================================

class AgentTask(BaseModel):
    """
    Agent 任务表

    记录每一次 Agent 任务的完整生命周期：
    任务参数 → 规划过程 → 执行步骤 → 反思过程 → 最终结果

    用于任务追踪、失败排查、审计与效果分析。
    """
    __tablename__ = "agent_tasks"
    __table_args__ = (
        Index("idx_agent_task_user_id", "user_id"),
        Index("idx_agent_task_conv_id", "conversation_id"),
        Index("idx_agent_task_status", "status"),
        Index("idx_agent_task_created_at", "created_at"),
        {"comment": "Agent任务表"},
    )

    task_id = Column(String(64), nullable=False, unique=True, comment="任务唯一ID")
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="用户ID",
    )
    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联会话ID",
    )
    knowledge_base_id = Column(
        Integer,
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联知识库ID",
    )

    title = Column(String(256), nullable=True, comment="任务标题")
    task_input = Column(Text, nullable=False, comment="任务输入（用户原始请求）")

    status = Column(
        String(32),
        nullable=False,
        default=AgentTaskStatus.PENDING.value,
        comment="任务状态: pending/planning/executing/reflecting/success/failed/cancelled",
    )

    # 规划过程
    plan = Column(
        JSON,
        nullable=True,
        comment="任务规划 [{step, tool, input, description}]",
    )

    # 执行步骤日志（逐步记录，便于复盘）
    execution_log = Column(
        JSON,
        nullable=True,
        comment="执行日志 [{step, tool, input, output, status, duration, reflection}]",
    )

    # 反思记录
    reflection_log = Column(
        JSON,
        nullable=True,
        comment="反思记录 [{retry_count, issue, fix_strategy}]",
    )

    # 结果
    result = Column(Text, nullable=True, comment="任务最终结果")
    result_data = Column(
        JSON,
        nullable=True,
        comment="结构化结果数据",
    )

    # 统计
    retry_count = Column(Integer, default=0, comment="重试次数")
    total_steps = Column(Integer, default=0, comment="执行步骤总数")
    duration_ms = Column(Integer, default=0, comment="总耗时（毫秒）")
    tokens_used = Column(Integer, default=0, comment="消耗token数")

    error_message = Column(Text, nullable=True, comment="错误信息")

    # 关系
    user = relationship("User", back_populates="agent_tasks")
    conversation = relationship("Conversation", back_populates="agent_tasks")


# ============================================================
# 9. 审计日志表
# ============================================================

class AuditLog(BaseModel):
    """
    审计日志表

    记录所有关键操作：登录、知识库管理、文档上传/删除、问答、Agent 任务、权限变更等。
    日志只追加，不修改、不删除（软删除也不建议）。
    """
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_user_id", "user_id"),
        Index("idx_audit_action", "action"),
        Index("idx_audit_result", "result"),
        Index("idx_audit_resource", "resource_type", "resource_id"),
        Index("idx_audit_created_at", "created_at"),
        {"comment": "审计日志表"},
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="操作用户ID（未登录操作为NULL）",
    )

    action = Column(String(64), nullable=False, index=True, comment="操作类型（见 AuditAction 枚举）")
    result = Column(
        String(32),
        nullable=False,
        default=AuditResult.SUCCESS.value,
        comment="操作结果: success/failed/permission_denied",
    )

    # 操作对象
    resource_type = Column(String(32), nullable=True, comment="资源类型: user/kb/doc/conv/agent_task")
    resource_id = Column(String(64), nullable=True, comment="资源ID")

    # 请求信息
    ip_address = Column(String(64), nullable=True, comment="客户端IP")
    user_agent = Column(String(512), nullable=True, comment="User-Agent")
    request_method = Column(String(16), nullable=True, comment="HTTP方法")
    request_path = Column(String(512), nullable=True, comment="请求路径")

    # 详情
    details = Column(
        JSON,
        nullable=True,
        comment="操作详情（JSON格式，便于扩展）",
    )
    error_message = Column(Text, nullable=True, comment="错误信息（失败时）")

    # 关系
    user = relationship("User", back_populates="audit_logs")


# ============================================================
# 10. 试卷表（课程试卷智能命题校验批改系统）
# ============================================================

class ExamPaper(BaseModel):
    """
    试卷表

    归属某个课程库（knowledge_bases），记录题型配置、题目集合、参考答案、
    双 Agent 完整执行轨迹（命题 → 逐题校验 → 重生成）。
    试卷题目/答案/轨迹均为结构化 JSON，不存文件。
    """
    __tablename__ = "exam_papers"
    __table_args__ = (
        Index("idx_exam_kb_id", "knowledge_base_id"),
        Index("idx_exam_creator_id", "creator_id"),
        Index("idx_exam_status", "status"),
        {"comment": "试卷表"},
    )

    knowledge_base_id = Column(
        Integer,
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        comment="归属课程库ID",
    )
    creator_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建者（教师）用户ID",
    )

    title = Column(String(256), nullable=False, comment="试卷标题")
    question_config = Column(
        JSON,
        nullable=True,
        comment="题型配置 {choice: 单选题数, fill: 填空题数, short: 简答题数}",
    )
    difficulty = Column(
        String(32),
        nullable=False,
        default="medium",
        comment="难度: easy/medium/hard",
    )

    # 题目列表（每题含答案、知识点、来源引用，见 ExamQuestionType）
    questions = Column(
        JSON,
        nullable=True,
        comment="题目列表 [{qid, type, stem, options, answer, knowledge_point, source_refs}]",
    )
    reference_answers = Column(
        JSON,
        nullable=True,
        comment="参考答案（与题目一一对应，便于单独导出）",
    )

    # 双 Agent 执行轨迹（逐轮记录：检索 → 出题 → 逐题校验 → 重生成）
    trace = Column(
        JSON,
        nullable=True,
        comment="双Agent完整执行轨迹 [{iteration, phase, detail}]",
    )

    iterate_count = Column(Integer, default=0, comment="实际迭代次数")
    total_score = Column(Integer, default=0, comment="试卷总分")
    status = Column(
        String(32),
        nullable=False,
        default=ExamPaperStatus.GENERATING.value,
        comment="状态: generating/ready/failed",
    )
    error_message = Column(Text, nullable=True, comment="生成失败原因")


# ============================================================
# 11. 答卷表（课程试卷智能命题校验批改系统）
# ============================================================

class AnswerSheet(BaseModel):
    """
    答卷表

    学生（read 权限）在线作答提交；客观题规则判分，主观题基于课程库课件溯源批改。
    批改详情 grading_details 每道主观题带课件原文片段来源引用。
    """
    __tablename__ = "answer_sheets"
    __table_args__ = (
        Index("idx_answer_exam_id", "exam_paper_id"),
        Index("idx_answer_student_id", "student_id"),
        Index("idx_answer_status", "status"),
        {"comment": "答卷表"},
    )

    exam_paper_id = Column(
        Integer,
        ForeignKey("exam_papers.id", ondelete="CASCADE"),
        nullable=False,
        comment="试卷ID",
    )
    student_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="学生用户ID",
    )

    answers = Column(
        JSON,
        nullable=True,
        comment="学生作答 [{qid, answer}]",
    )

    objective_score = Column(Integer, default=0, comment="客观题得分")
    subjective_score = Column(Integer, default=0, comment="主观题得分")
    total_score = Column(Integer, default=0, comment="总分")

    grading_details = Column(
        JSON,
        nullable=True,
        comment="批改详情 [{qid, score, strengths, missing, source_refs}]，source_refs 为课件原文片段引用",
    )

    status = Column(
        String(32),
        nullable=False,
        default=AnswerSheetStatus.SUBMITTED.value,
        comment="状态: submitted/grading/graded",
    )
    error_message = Column(Text, nullable=True, comment="批改失败原因")
    submitted_at = Column(DateTime, nullable=True, comment="提交时间")
