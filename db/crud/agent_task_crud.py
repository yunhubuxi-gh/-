"""
Agent 任务 CRUD
"""
from __future__ import annotations

from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

from db.models import AgentTask
from db.schemas import AgentTaskCreate
from config.constants import AgentTaskStatus
from utils.logger import get_logger

logger = get_logger(__name__)


class AgentTaskCRUD:
    """Agent 任务 CRUD"""

    model = AgentTask

    def get_by_id(self, db: Session, task_db_id: int) -> Optional[AgentTask]:
        return db.query(AgentTask).filter(
            AgentTask.id == task_db_id,
            AgentTask.is_deleted == False,  # noqa: E712
        ).first()

    def get_by_task_id(self, db: Session, task_id: str) -> Optional[AgentTask]:
        """通过业务 task_id 查询"""
        return db.query(AgentTask).filter(
            AgentTask.task_id == task_id,
            AgentTask.is_deleted == False,  # noqa: E712
        ).first()

    def get_list_by_user(
        self,
        db: Session,
        user_id: int,
        status: Optional[str] = None,
        kb_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[AgentTask], int]:
        query = db.query(AgentTask).filter(
            AgentTask.user_id == user_id,
            AgentTask.is_deleted == False,  # noqa: E712
        )
        if status:
            query = query.filter(AgentTask.status == status)
        if kb_id:
            query = query.filter(AgentTask.knowledge_base_id == kb_id)

        total = query.count()
        tasks = query.order_by(AgentTask.created_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        return tasks, total

    def create(self, db: Session, user_id: int, obj_in: AgentTaskCreate, task_id: str) -> AgentTask:
        data = obj_in.model_dump()
        data["user_id"] = user_id
        data["task_id"] = task_id
        data["status"] = AgentTaskStatus.PENDING.value
        task = AgentTask(**data)
        db.add(task)
        db.commit()
        db.refresh(task)
        logger.info(f"创建Agent任务: task_id={task_id}, user_id={user_id}")
        return task

    def update_status(
        self,
        db: Session,
        task_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> Optional[AgentTask]:
        task = self.get_by_task_id(db, task_id)
        if not task:
            return None
        task.status = status
        if error_message is not None:
            task.error_message = error_message
        db.commit()
        db.refresh(task)
        logger.debug(f"Agent任务状态: task_id={task_id}, status={status}")
        return task

    def update_plan(self, db: Session, task_id: str, plan: list) -> Optional[AgentTask]:
        task = self.get_by_task_id(db, task_id)
        if not task:
            return None
        task.plan = plan
        db.commit()
        db.refresh(task)
        return task

    def append_execution_log(self, db: Session, task_id: str, step_log: dict) -> Optional[AgentTask]:
        """追加执行日志步骤"""
        task = self.get_by_task_id(db, task_id)
        if not task:
            return None
        log = task.execution_log or []
        log.append(step_log)
        task.execution_log = log
        task.total_steps = len(log)
        db.commit()
        db.refresh(task)
        return task

    def append_reflection_log(self, db: Session, task_id: str, reflection: dict) -> Optional[AgentTask]:
        task = self.get_by_task_id(db, task_id)
        if not task:
            return None
        log = task.reflection_log or []
        log.append(reflection)
        task.reflection_log = log
        task.retry_count = len(log)
        db.commit()
        db.refresh(task)
        return task

    def set_result(
        self,
        db: Session,
        task_id: str,
        result: str,
        result_data: Optional[dict] = None,
        duration_ms: int = 0,
        tokens_used: int = 0,
    ) -> Optional[AgentTask]:
        task = self.get_by_task_id(db, task_id)
        if not task:
            return None
        task.result = result
        task.result_data = result_data
        task.duration_ms = duration_ms
        task.tokens_used = tokens_used
        task.status = AgentTaskStatus.SUCCESS.value
        db.commit()
        db.refresh(task)
        return task

    def delete(self, db: Session, task_id: str) -> bool:
        task = self.get_by_task_id(db, task_id)
        if not task:
            return False
        task.is_deleted = True
        db.commit()
        return True


# 单例
agent_task_crud = AgentTaskCRUD()
