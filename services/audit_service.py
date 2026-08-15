"""
审计日志服务（audit_service）

职责：
- 只做审计日志查询（分页 / 条件过滤）
- 审计日志写入全部统一复用 services.write_audit_log
  （内部走 utils.logger.log_audit 文件审计 + db.crud.audit_log_crud 数据库审计），
  本服务层不实现任何写日志逻辑

依赖：
- db.crud.audit_log_crud.query：分页查询
- db.schemas.AuditLogQuery：查询参数
- utils.response.page_result：分页结果封装
"""
from __future__ import annotations

from typing import Dict, Any

from db.schemas import AuditLogQuery
from db.crud import audit_log_crud
from utils.response import page_result
from utils.logger import get_logger

logger = get_logger(__name__)


class AuditService:
    """审计日志服务（只读查询）"""

    def query(self, db, query: AuditLogQuery) -> Dict[str, Any]:
        """分页查询审计日志"""
        logs, total = audit_log_crud.query(
            db,
            user_id=query.user_id,
            action=query.action,
            result=query.result,
            resource_type=query.resource_type,
            resource_id=query.resource_id,
            start_time=query.start_time,
            end_time=query.end_time,
            page=query.page,
            page_size=query.page_size,
        )
        items = [log.to_dict() for log in logs]
        return page_result(items, total, query.page, query.page_size)

    def count_by_action(self, db, action: str, days: int = 7) -> int:
        """统计某操作最近 N 天次数（报表/监控用）"""
        return audit_log_crud.count_by_action(db, action, days)


# 单例
audit_service = AuditService()
