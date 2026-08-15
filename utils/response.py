"""
统一响应封装
所有 API 接口返回格式统一，便于前端统一处理。

响应格式：
{
    "code": 0,              // 业务状态码，0 表示成功
    "message": "成功",       // 消息
    "data": { ... },        // 数据体
    "timestamp": 1700000000 // 时间戳
}
"""
from __future__ import annotations

import time
from typing import Any, Generic, List, TypeVar
from pydantic import BaseModel, Field

from utils.error_codes import ErrorCode, SUCCESS, UNKNOWN_ERROR

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应模型"""
    code: int = Field(default=0, description="业务状态码，0 表示成功")
    message: str = Field(default="成功", description="响应消息")
    data: T | None = Field(default=None, description="响应数据")
    timestamp: int = Field(default_factory=lambda: int(time.time()), description="时间戳")


class PageResult(BaseModel, Generic[T]):
    """分页结果"""
    items: List[T] = Field(default_factory=list, description="数据列表")
    total: int = Field(default=0, description="总条数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页条数")
    total_pages: int = Field(default=0, description="总页数")


def success_response(data: Any = None, message: str = "成功") -> dict:
    """
    成功响应

    Args:
        data: 响应数据
        message: 成功消息

    Returns:
        统一格式的响应字典
    """
    return {
        "code": SUCCESS.code,
        "message": message,
        "data": data,
        "timestamp": int(time.time()),
    }


def fail_response(error_code: ErrorCode, message: str | None = None, details: dict | None = None) -> dict:
    """
    业务失败响应（已知错误，如参数错误、权限不足等）

    Args:
        error_code: 错误码对象
        message: 覆盖默认消息
        details: 详细错误信息

    Returns:
        统一格式的响应字典
    """
    return {
        "code": error_code.code,
        "message": message or error_code.message,
        "data": details,
        "timestamp": int(time.time()),
    }


def error_response(message: str = "系统内部错误", details: dict | None = None) -> dict:
    """
    系统错误响应（未捕获的异常）

    Args:
        message: 错误消息
        details: 详细信息（生产环境可隐藏）

    Returns:
        统一格式的响应字典
    """
    return {
        "code": UNKNOWN_ERROR.code,
        "message": message,
        "data": details,
        "timestamp": int(time.time()),
    }


def page_result(
    items: List[Any],
    total: int,
    page: int,
    page_size: int,
) -> dict:
    """
    构造分页结果

    Args:
        items: 当前页数据
        total: 总条数
        page: 当前页码
        page_size: 每页条数

    Returns:
        分页数据字典
    """
    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
