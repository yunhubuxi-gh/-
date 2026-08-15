"""
请求日志中间件

记录每次 HTTP 请求的：方法、路径、状态码、用户 ID（若已鉴权）、耗时。
用户 ID 由 JWT 鉴权依赖（api.deps.get_current_user）写入 request.state.user_id。
"""
from __future__ import annotations

import time

from starlette.requests import Request

from utils.logger import get_logger

logger = get_logger(__name__)


async def request_log_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    user_id = getattr(request.state, "user_id", None)
    logger.info(
        f"HTTP {request.method} {request.url.path} -> {response.status_code} "
        f"| user={user_id or 'anonymous'} | {duration_ms}ms"
    )
    return response
