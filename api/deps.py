"""
JWT 鉴权依赖

供路由层通过 Depends(get_current_user) 注入当前登录用户。
- 从 Authorization: Bearer <token> 读取 access_token
- 复用 services.auth_service.get_current_user 完成解析与用户状态校验
- 校验失败抛出 AuthException（由全局异常处理器转 401 标准化返回体）
- 同时把 user_id 写入 request.state，供请求日志中间件记录
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from db.session import get_db
from db.models import User

# auto_error=False：令牌缺失时不抛 FastAPI 默认异常，交给 auth_service 抛出统一 AuthException
security = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """解析 access_token，返回当前登录用户（复用 service 层逻辑，不重复实现 JWT）"""
    from services import auth_service
    token = credentials.credentials if credentials else None
    user = auth_service.get_current_user(db, token)
    # 供中间件记录请求用户
    request.state.user_id = user.id
    return user
