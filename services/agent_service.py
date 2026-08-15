"""
Agent 任务服务（agent_service）

职责：
- 接收业务参数，调用 ai.agent_langgraph.AgentManager.execute 统一入口执行 Agent 任务
- 任务记录：完全复用 db 已定义的 agent_tasks ORM 模型，由 AgentManager 内部调用
  db.crud.agent_task_crud 写入（禁止新建数据表）
- 长期记忆路径：业务层统一从 config（agent_config.get_agent_config().long_term_dir）读取，
  严禁代码硬编码磁盘路径
- 权限：任务涉及的知识库需 read+ 访问权限
- 审计：任务创建/完成/失败由 AgentManager 内部统一写入
  （utils.logger.log_audit + db.crud.audit_log_crud），本服务不自行实现日志

依赖：
- ai.agent_langgraph.agent_manager.AgentManager：统一执行入口（不重写 LangGraph 工作流）
- db.crud.agent_task_crud：任务表（复用）
- ai.agent_langgraph.agent_config.get_agent_config：长期记忆路径等配置
- db.crud.conversation_crud：Agent 会话（type=agent）
"""
from __future__ import annotations

from typing import Dict, Any, Optional, List

from config.constants import KBUserRole, ConversationType, AuditAction, AuditResult
from db.schemas import AgentTaskCreate, ConversationCreate
from db.crud import agent_task_crud, conversation_crud, kb_crud
from utils.permission import has_permission
from utils.exceptions import (
    ResourceNotFoundException,
    ValidationException,
    PermissionException,
)
from utils.error_codes import (
    KB_NOT_FOUND,
    KB_NO_PERMISSION,
    AGENT_TASK_NOT_FOUND,
    INVALID_PARAMS,
)
from utils.response import page_result
from utils.logger import get_logger
from services import write_audit_log

logger = get_logger(__name__)


class AgentService:
    """Agent 任务服务"""

    def __init__(self, agent_manager=None):
        # 可注入（测试用 Fake），缺省懒加载真实 AgentManager
        self.agent_manager = agent_manager

    def _get_manager(self):
        if self.agent_manager is None:
            from ai.agent_langgraph.agent_manager import AgentManager
            from ai.agent_langgraph.memory import LongTermMemory
            from ai.agent_langgraph.agent_config import get_agent_config

            cfg = get_agent_config()
            # 长期记忆持久化路径统一从全局 config 读取，严禁代码硬编码磁盘路径
            self.agent_manager = AgentManager(
                long_memory=LongTermMemory(storage_dir=cfg.long_term_dir),
            )
        return self.agent_manager

    # ============================================================
    # 任务提交 / 执行
    # ============================================================

    def submit(
        self,
        db,
        user_id: int,
        data: AgentTaskCreate,
        knowledge_base_ids: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """
        提交并执行 Agent 任务。

        - 解析授权知识库列表（data.knowledge_base_id 或外部传入）
        - 逐个校验 read 权限，越权写审计（permission_denied）
        - 无会话时自动创建 agent 类型会话
        - 调用 AgentManager.execute（内部完成规划-执行-反思闭环、写 agent_tasks、写审计）
        """
        # 1. 解析知识库
        kb_ids = self._resolve_kb_ids(data, knowledge_base_ids)

        # 2. 权限校验（每个库至少 read）
        for kb_id in kb_ids:
            self._check_read(db, kb_id, user_id, AuditAction.AGENT_TASK_CREATE.value)

        # 3. 会话（agent 类型）
        conv_id = data.conversation_id
        if conv_id is None:
            conv = conversation_crud.create(
                db, user_id,
                ConversationCreate(
                    title=data.title or data.task_input[:30],
                    knowledge_base_id=data.knowledge_base_id,
                    type=ConversationType.AGENT.value,
                ),
            )
            conv_id = conv.id
        else:
            conv = conversation_crud.get_by_id(db, conv_id)
            if not conv or conv.is_deleted:
                raise ResourceNotFoundException(INVALID_PARAMS, f"会话 {conv_id} 不存在")
            if conv.user_id != user_id:
                raise PermissionException(
                    KB_NO_PERMISSION, "无权使用该会话", {"resource": f"conv_{conv_id}"},
                )

        # 4. 执行 Agent 任务（AgentManager 内部写 agent_tasks + 审计）
        manager = self._get_manager()
        result = manager.execute(
            user_id=user_id,
            task_input=data.task_input,
            knowledge_base_ids=kb_ids,
            conversation_id=conv_id,
            db=db,
            title=data.title,
        )

        # 5. 执行失败时补一条业务层失败审计（便于审计服务聚合）
        if not result.success:
            write_audit_log(
                db, user_id, AuditAction.AGENT_TASK_COMPLETE.value,
                result=AuditResult.FAILED.value,
                resource_type="agent_task", resource_id=result.task_id,
                details={"task_input": data.task_input[:100], "retry_count": result.retry_count},
                error_message=result.error,
            )
        return result.to_dict()

    # ============================================================
    # 任务查询 / 管理
    # ============================================================

    def get_task(self, db, user_id: int, task_id: str) -> Dict[str, Any]:
        """任务详情（仅归属用户本人，含规划/执行日志/反思记录）"""
        task = agent_task_crud.get_by_task_id(db, task_id)
        if not task or task.user_id != user_id:
            raise ResourceNotFoundException(AGENT_TASK_NOT_FOUND, "任务不存在")
        return self._to_task_detail(task)

    def list_tasks(
        self, db, user_id: int, status: Optional[str] = None,
        kb_id: Optional[int] = None, page: int = 1, page_size: int = 20,
    ) -> Dict[str, Any]:
        """列出当前用户的任务"""
        tasks, total = agent_task_crud.get_list_by_user(
            db, user_id, status, kb_id, page, page_size,
        )
        return page_result([t.to_dict() for t in tasks], total, page, page_size)

    # ============================================================
    # 内部工具
    # ============================================================

    @staticmethod
    def _resolve_kb_ids(data: AgentTaskCreate, knowledge_base_ids: Optional[List[Any]]) -> List[int]:
        """合并任务关联知识库与外部传入知识库，去重"""
        ids: List[int] = []
        if data.knowledge_base_id is not None:
            ids.append(int(data.knowledge_base_id))
        if knowledge_base_ids:
            for i in knowledge_base_ids:
                if int(i) not in ids:
                    ids.append(int(i))
        if not ids:
            raise ValidationException(INVALID_PARAMS, "缺少知识库 ID")
        return ids

    def _check_read(self, db, kb_id: int, user_id: int, action: str) -> None:
        """校验知识库 read 权限，越权抛 PermissionException 并写审计"""
        if not kb_crud.get_by_id(db, kb_id):
            raise ResourceNotFoundException(KB_NOT_FOUND, f"知识库 {kb_id} 不存在")
        role = kb_crud.get_user_role(db, kb_id, user_id)
        if role is None or not has_permission(role, KBUserRole.READ):
            write_audit_log(
                db, user_id, action,
                result=AuditResult.PERMISSION_DENIED.value,
                resource_type="kb", resource_id=kb_id,
                details={"op": "agent_submit", "user_role": role, "required": "read"},
            )
            raise PermissionException(
                KB_NO_PERMISSION, "无该知识库访问权限", {"resource": f"kb_{kb_id}"},
            )

    @staticmethod
    def _to_task_detail(task) -> Dict[str, Any]:
        d = task.to_dict()
        for key in ("plan", "execution_log", "reflection_log"):
            d[key] = getattr(task, key, None)
        return d


# 单例
agent_service = AgentService()
