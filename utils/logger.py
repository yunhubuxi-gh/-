"""
统一日志工具
提供普通日志器与审计日志器的获取函数。
"""
from __future__ import annotations

import logging
import logging.config


def get_logger(name: str) -> logging.Logger:
    """
    获取普通日志器。

    Args:
        name: 日志器名称，建议传 __name__

    Returns:
        logging.Logger 实例
    """
    return logging.getLogger(name)


def get_audit_logger() -> logging.Logger:
    """
    获取审计日志器。
    审计日志独立通道、独立文件、保留时间更长。

    Returns:
        审计专用 Logger
    """
    return logging.getLogger("audit")


def log_audit(
    user_id: str | None,
    action: str,
    resource: str = "",
    result: str = "success",
    details: str = "",
    ip: str = "",
) -> None:
    """
    便捷记录一条审计日志。

    Args:
        user_id: 操作用户 ID（可为空，如登录前操作）
        action: 操作类型（见 AuditAction 枚举）
        resource: 操作资源标识（如 kb_123 / doc_456）
        result: 操作结果（success / failed / permission_denied）
        details: 详细描述
        ip: 客户端 IP
    """
    audit_logger = get_audit_logger()
    msg = (
        f"user={user_id or 'anonymous'} | action={action} | "
        f"resource={resource} | result={result} | ip={ip} | "
        f"details={details}"
    )
    audit_logger.info(msg)
