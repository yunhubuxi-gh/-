"""
全局异常处理器

把 service 层抛出的自定义业务异常统一转换为标准化 HTTP 返回体。
接口层 / service 层均不做 HTTP 响应封装，只抛异常，全部在此处收敛。

返回体结构（与 utils.response 保持一致）：
    {"code": <错误码>, "message": <消息>, "data": <详情>, "timestamp": <时间戳>}

覆盖：
- AppException 及其子类（AuthException / PermissionException / ResourceNotFoundException /
  ValidationException / RAGException / AgentException / FileOperationException）→ 按错误码 HTTP 状态码
- RequestValidationError（pydantic 请求体/参数校验失败）→ 422 + INVALID_PARAMS
- StarletteHTTPException（框架级 404/405 等）→ 保持原状态码
- Exception（未捕获系统异常）→ 500
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from utils.exceptions import AppException
from utils.error_codes import INVALID_PARAMS, UNKNOWN_ERROR, RESOURCE_NOT_FOUND
from utils.response import fail_response, error_response
from utils.logger import get_logger

logger = get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """向 FastAPI 实例挂载全部异常处理器"""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        logger.warning(f"业务异常: [{exc.code}] {exc.message}")
        return JSONResponse(
            status_code=exc.http_status,
            content=fail_response(exc.error_code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=fail_response(INVALID_PARAMS, "请求参数校验失败", {"errors": exc.errors()}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        code = RESOURCE_NOT_FOUND if exc.status_code == 404 else UNKNOWN_ERROR
        return JSONResponse(
            status_code=exc.status_code,
            content=fail_response(code, str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.exception(f"系统异常: {exc}")
        return JSONResponse(status_code=500, content=error_response("系统内部错误"))
