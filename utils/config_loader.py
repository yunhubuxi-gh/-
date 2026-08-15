"""
配置加载器封装
对 config.settings 做一层轻量封装，提供更便捷的访问接口。
如果未来需要支持配置热更新、多环境配置文件合并，都在此处扩展。
"""
from __future__ import annotations

from typing import Any

from config.settings import Settings, settings as _settings
from utils.logger import get_logger

logger = get_logger(__name__)


class ConfigLoader:
    """配置加载器封装类"""

    def __init__(self, settings_instance: Settings):
        self._settings = settings_instance

    @property
    def raw(self) -> Settings:
        """获取原始 Settings 对象"""
        return self._settings

    def get(self, key: str, default: Any = None) -> Any:
        """
        按属性名获取配置值，支持点号嵌套（如 "database.url"）。
        当前为单层配置，直接取属性。

        Args:
            key: 配置键名
            default: 默认值

        Returns:
            配置值
        """
        value = getattr(self._settings, key, default)
        return value

    def reload(self) -> None:
        """
        重新加载配置（热更新）。
        注意：pydantic-settings 默认读取环境变量，环境变量变更后需调用此方法。
        """
        from config.settings import get_settings
        get_settings.cache_clear()
        from config.settings import get_settings as _gs
        self._settings = _gs()
        logger.info("配置已重新加载")


# 全局单例
config_loader = ConfigLoader(_settings)


def get_config() -> ConfigLoader:
    """获取配置加载器单例"""
    return config_loader
