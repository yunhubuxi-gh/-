"""
日志配置模块
- 支持多级别输出（DEBUG/INFO/WARNING/ERROR）
- 控制台 + 文件双输出
- 文件按天滚动，自动清理过期日志
- 独立审计日志通道（audit logger）
"""
from __future__ import annotations

import os
import logging
import logging.handlers
from pathlib import Path

from config.settings import settings


_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _ensure_log_dir() -> Path:
    """确保日志目录存在"""
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_logging() -> None:
    """
    初始化全局日志配置。
    应在应用启动时调用一次。
    """
    log_dir = _ensure_log_dir()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # 根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # 避免重复添加 handler（多次调用时）
    if root_logger.handlers:
        return

    formatter = logging.Formatter(_LOG_FORMAT, _DATE_FORMAT)

    # ---------- 控制台 handler ----------
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # ---------- 应用日志文件 handler（按天滚动）----------
    app_file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_dir / "app.log"),
        when="midnight",
        interval=1,
        backupCount=30,  # 保留 30 天
        encoding="utf-8",
    )
    app_file_handler.setLevel(log_level)
    app_file_handler.setFormatter(formatter)
    app_file_handler.suffix = "%Y-%m-%d"
    root_logger.addHandler(app_file_handler)

    # ---------- 错误日志文件 handler ----------
    error_file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_dir / "error.log"),
        when="midnight",
        interval=1,
        backupCount=60,  # 错误日志保留 60 天
        encoding="utf-8",
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(formatter)
    error_file_handler.suffix = "%Y-%m-%d"
    root_logger.addHandler(error_file_handler)

    # ---------- 审计日志（独立 logger + 独立文件）----------
    audit_logger = logging.getLogger("audit")
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False  # 不向 root 传播，避免重复记录

    audit_file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_dir / "audit.log"),
        when="midnight",
        interval=1,
        backupCount=90,  # 审计日志保留 90 天
        encoding="utf-8",
    )
    audit_formatter = logging.Formatter(
        "%(asctime)s | AUDIT | %(message)s", _DATE_FORMAT
    )
    audit_file_handler.setFormatter(audit_formatter)
    audit_logger.addHandler(audit_file_handler)

    # 同时把审计日志输出到控制台（开发环境方便查看）
    if settings.debug:
        audit_console = logging.StreamHandler()
        audit_console.setFormatter(audit_formatter)
        audit_logger.addHandler(audit_console)

    root_logger.info(f"日志系统初始化完成，日志目录: {log_dir.resolve()}")
