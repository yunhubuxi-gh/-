"""
Agent 模块配置

Agent 特有配置集中在此处，全部配置化，禁止魔法数字。
已存在的通用配置（agent_max_retry / agent_short_term_memory_window /
agent_long_term_memory_enabled）从 config.settings 读取；Agent 特有的补充配置
通过环境变量（AGENT_ 前缀）覆盖，避免修改步骤1的 settings.py。

读取优先级：环境变量 > settings 已有字段 > 默认值。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class AgentConfig:
    """Agent 执行配置（全部配置化）"""

    # 反思重试最大次数（超过则停止，避免死循环）
    max_retry: int = 3
    # 单次任务最多规划的步骤数
    max_plan_steps: int = 5
    # 短期记忆滑动窗口大小（消息条数）
    short_term_window: int = 10
    # 长期记忆是否启用
    long_term_enabled: bool = True
    # 长期记忆每个用户最多保留的偏好条数（防止上下文溢出）
    long_term_max_items: int = 50
    # 长期记忆磁盘存储目录
    long_term_dir: str = "./data/long_term_memory"
    # 检索长期记忆时返回的条数
    long_term_top_k: int = 3


@lru_cache(maxsize=1)
def get_agent_config() -> AgentConfig:
    """
    获取 Agent 配置单例。
    - 优先读 config.settings 中已有的 agent_* 字段
    - Agent 特有字段读 AGENT_ 前缀环境变量
    """
    cfg = AgentConfig(
        max_retry=getattr(settings, "agent_max_retry", 3),
        short_term_window=getattr(settings, "agent_short_term_memory_window", 10),
        long_term_enabled=getattr(settings, "agent_long_term_memory_enabled", True),
        max_plan_steps=_env_int("AGENT_MAX_PLAN_STEPS", 5),
        long_term_max_items=_env_int("AGENT_LONG_TERM_MAX_ITEMS", 50),
        long_term_dir=os.getenv("AGENT_LONG_TERM_DIR", "./data/long_term_memory"),
        long_term_top_k=_env_int("AGENT_LONG_TERM_TOP_K", 3),
    )
    logger.debug(f"Agent 配置加载完成: {cfg}")
    return cfg
