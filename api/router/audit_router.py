"""
审计日志路由（audit_router）

端点（受 JWT 保护）：
- GET /logs   分页查询审计日志（只读）

审计日志写入统一走 services.write_audit_log（service 层），本层不写日志。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from db.schemas import AuditLogQuery
from db.models import User
from api.deps import get_current_user
from utils.response import success_response
from services import audit_service

router = APIRouter()


@router.get("/logs")
def query_logs(
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    result: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = AuditLogQuery(
        user_id=user_id, action=action, result=result,
        resource_type=resource_type, resource_id=resource_id,
        page=page, page_size=page_size,
    )
    return success_response(audit_service.query(db, query))
