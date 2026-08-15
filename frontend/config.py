"""
前端网络配置

- API base_url 统一读取全局 config（config.settings），严禁在页面 / api_client 中硬编码后端地址。
- 超时、轮询间隔等网络参数集中于此，环境变量可覆盖。

读取规则：
- base_url：优先环境变量 FRONTEND_API_BASE_URL；否则由全局 config 的 api_host / api_port 派生，
  api_host 为 0.0.0.0 / 空时回退 127.0.0.1。
"""
from __future__ import annotations

import os

from config.settings import settings


def _resolve_base_url() -> str:
    """解析后端 API base_url（不硬编码地址）"""
    env = os.getenv("FRONTEND_API_BASE_URL", "").strip()
    if env:
        return env.rstrip("/")

    host = (settings.api_host or "").strip()
    if host in ("", "0.0.0.0"):
        host = "127.0.0.1"
    return f"http://{host}:{settings.api_port}"


# 后端 API 基础地址（统一出口）
API_BASE_URL: str = _resolve_base_url()

# 请求超时（秒）
TIMEOUT: int = int(os.getenv("FRONTEND_TIMEOUT", "60"))

# 轮询间隔（秒）
POLL_INTERVAL_SECONDS: float = float(os.getenv("FRONTEND_POLL_INTERVAL", "1.0"))

# 轮询最大等待时长（秒）
POLL_MAX_WAIT_SECONDS: float = float(os.getenv("FRONTEND_POLL_MAX_WAIT", "180"))

# 分页默认值
DEFAULT_PAGE_SIZE: int = 12
