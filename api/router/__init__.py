"""
路由模块聚合

6 个路由：
- auth_router      认证（注册/登录/刷新令牌/修改密码/当前用户）
- kb_router        知识库 CRUD + 成员权限管理
- document_router  文档上传（异步）/列表/版本/下载/删除/重建
- chat_router      会话创建/问答/消息列表
- agent_router     Agent 任务提交/查询
- audit_router     审计日志查询
"""
from __future__ import annotations

from api.router.auth_router import router as auth_router
from api.router.kb_router import router as kb_router
from api.router.document_router import router as document_router
from api.router.chat_router import router as chat_router
from api.router.agent_router import router as agent_router
from api.router.audit_router import router as audit_router
from api.router.exam_router import router as exam_router

__all__ = [
    "auth_router",
    "kb_router",
    "document_router",
    "chat_router",
    "agent_router",
    "audit_router",
    "exam_router",
]
