"""
Agent 任务路由（agent_router）

端点（全部受 JWT 保护）：
- POST /tasks          提交 Agent 任务（复用 AgentManager + agent_tasks 表）
- GET  /tasks          任务列表
- GET  /tasks/{task_id}  任务详情（含规划/执行日志/反思记录）
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from db.schemas import AgentTaskCreate
from db.models import User
from api.deps import get_current_user
from utils.response import success_response
from services import agent_service

router = APIRouter()


@router.post("/tasks")
def submit_task(
    data: AgentTaskCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(agent_service.submit(db, user.id, data), "Agent 任务已提交")


@router.get("/tasks")
def list_tasks(
    status: Optional[str] = None,
    kb_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(agent_service.list_tasks(db, user.id, status, kb_id, page, page_size))


@router.get("/tasks/{task_id}")
def get_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return success_response(agent_service.get_task(db, user.id, task_id))
