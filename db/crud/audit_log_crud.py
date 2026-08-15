"""
审计日志 CRUD
日志只追加，不修改，不删除。
"""
from __future__ import annotations

from typing import Optional, List, Tuple, Any
from datetime import datetime
from sqlalchemy.orm import Session

from db.models import AuditLog
from utils.logger import get_logger

logger = get_logger(__name__)


class AuditLogCRUD:
    """审计日志 CRUD"""

    model = AuditLog

    def get_by_id(self, db: Session, log_id: int) -> Optional[AuditLog]:
        return db.query(AuditLog).filter(AuditLog.id == log_id).first()

    def create(
        self,
        db: Session,
        user_id: Optional[int],
        action: str,
        result: str = "success",
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_method: Optional[str] = None,
        request_path: Optional[str] = None,
        details: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> AuditLog:
        """记录一条审计日志"""
        log = AuditLog(
            user_id=user_id,
            action=action,
            result=result,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            ip_address=ip_address,
            user_agent=user_agent,
            request_method=request_method,
            request_path=request_path,
            details=details,
            error_message=error_message,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    def query(
        self,
        db: Session,
        user_id: Optional[int] = None,
        action: Optional[str] = None,
        result: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[AuditLog], int]:
        """分页查询审计日志"""
        query = db.query(AuditLog)

        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        if action:
            query = query.filter(AuditLog.action == action)
        if result:
            query = query.filter(AuditLog.result == result)
        if resource_type:
            query = query.filter(AuditLog.resource_type == resource_type)
        if resource_id:
            query = query.filter(AuditLog.resource_id == resource_id)
        if start_time:
            query = query.filter(AuditLog.created_at >= start_time)
        if end_time:
            query = query.filter(AuditLog.created_at <= end_time)

        total = query.count()
        logs = query.order_by(AuditLog.id.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        return logs, total

    def count_by_action(self, db: Session, action: str, days: int = 7) -> int:
        """统计某操作最近 N 天的次数"""
        from sqlalchemy import func
        from datetime import timedelta
        since = datetime.utcnow() - timedelta(days=days)
        return db.query(AuditLog).filter(
            AuditLog.action == action,
            AuditLog.created_at >= since,
        ).count()


# 单例
audit_log_crud = AuditLogCRUD()
