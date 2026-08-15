"""
config 配置层

集中管理项目所有配置，包括：
- settings:  全局配置单例（从 .env / 环境变量加载）
- constants: 常量与枚举定义
- logging_config: 日志配置
"""
from config.settings import settings, get_settings
from config.constants import *  # noqa: F401,F403
from config.logging_config import setup_logging

__all__ = [
    "settings",
    "get_settings",
    "setup_logging",
]
