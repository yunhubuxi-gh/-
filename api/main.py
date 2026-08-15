"""
FastAPI 主入口

职责：
- 创建 FastAPI 实例（读取 config 的应用名/版本/debug）
- 注册 CORS 跨域（来源读取 config.settings.cors_origins）
- 注册请求日志中间件
- 挂载全局异常处理器
- 注册全部路由（/api/v1 前缀）

启动：
    uvicorn api.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from api.handlers import register_exception_handlers
from api.middleware import request_log_middleware
from api.router import (
    auth_router,
    kb_router,
    document_router,
    chat_router,
    agent_router,
    audit_router,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
    )

    # CORS 跨域（来源读取 config）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 请求日志中间件
    app.middleware("http")(request_log_middleware)

    # 全局异常处理器
    register_exception_handlers(app)

    # 注册路由
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["认证"])
    app.include_router(kb_router, prefix="/api/v1/kb", tags=["知识库"])
    app.include_router(document_router, prefix="/api/v1", tags=["文档"])
    app.include_router(chat_router, prefix="/api/v1/chat", tags=["会话问答"])
    app.include_router(agent_router, prefix="/api/v1/agent", tags=["Agent 任务"])
    app.include_router(audit_router, prefix="/api/v1/audit", tags=["审计日志"])

    return app


app = create_app()
