"""
业务服务层（Service Layer）

职责：
- 承接上层（API / UI）请求，编排调用 db CRUD / RAG 引擎 / Agent 智能层 / utils 通用工具
- 落地知识库四级权限校验（owner/admin/write/read），拦截越权操作并写审计
- 所有业务变更操作统一通过本模块的 write_audit_log() 写入审计日志
  （文件审计走 utils.logger.log_audit，数据库审计走 db.crud.audit_log_crud，禁止自行实现日志）

模块划分（6 个业务模块）：
- auth_service：用户认证（注册/登录/双令牌/密码）
- kb_service：知识库 CRUD + 成员权限管理
- document_service：文档上传 / 解析向量化 / 版本管理 / 删除
- chat_service：会话管理 + RAG 问答
- agent_service：Agent 任务编排（复用 agent_langgraph 统一入口 + agent_tasks 表）
- audit_service：审计日志查询（只读，不写日志）

依赖调用规则（严格遵循）：
- 数据库操作 -> 全部走 db.crud，不写原生 SQL
- RAG 能力 -> 走 ai.rag_engine 对外入口（RagPipeline），不重写解析/召回
- Agent 能力 -> 走 ai.agent_langgraph 统一入口（AgentManager.execute），不重写工作流
- 通用能力 -> 全部复用 utils（异常/错误码/文件安全/权限/异步任务/审计）
"""
from __future__ import annotations

from utils.logger import get_logger, log_audit

logger = get_logger(__name__)


def write_audit_log(
    db,
    user_id,
    action: str,
    result: str = "success",
    resource_type: str | None = None,
    resource_id: str | int | None = None,
    details: dict | None = None,
    error_message: str | None = None,
) -> None:
    """
    统一审计日志写入（所有业务变更操作必须调用本函数，禁止自行实现日志）。

    两路写入：
    1. 文件审计：utils.logger.log_audit（权威通道）
    2. 数据库审计：db.crud.audit_log_crud.create（提供 db 会话时）

    Args:
        db: SQLAlchemy Session（可为 None，此时仅写文件审计）
        user_id: 操作用户 ID
        action: 操作类型（AuditAction 枚举值）
        result: 操作结果（success/failed/permission_denied）
        resource_type: 资源类型（user/kb/doc/conv/agent_task）
        resource_id: 资源 ID
        details: 操作详情（需 JSON 可序列化）
        error_message: 失败信息
    """
    # 文件审计（权威通道，禁止自行实现日志）
    log_audit(
        user_id=str(user_id) if user_id is not None else None,
        action=action,
        resource=(
            f"{resource_type}_{resource_id}"
            if resource_type and resource_id is not None
            else (resource_type or "")
        ),
        result=result,
        details=str(details or ""),
    )

    # 数据库审计（db 提供时）
    if db is not None:
        try:
            from db.crud import audit_log_crud
            audit_log_crud.create(
                db,
                user_id=user_id,
                action=action,
                result=result,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
                error_message=error_message,
            )
        except Exception as e:
            logger.warning(f"写数据库审计日志失败: {e}")


# 导出的 6 个业务服务单例（全部懒加载真实组件，import 不触发模型/网络加载）
from services.auth_service import AuthService, auth_service
from services.kb_service import KBService, kb_service
from services.document_service import DocumentService, document_service
from services.chat_service import ChatService, chat_service
from services.agent_service import AgentService, agent_service
from services.audit_service import AuditService, audit_service

__all__ = [
    "write_audit_log",
    "AuthService", "auth_service",
    "KBService", "kb_service",
    "DocumentService", "document_service",
    "ChatService", "chat_service",
    "AgentService", "agent_service",
    "AuditService", "audit_service",
]
