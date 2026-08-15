"""
认证路由（auth_router）

端点：
- POST /register         注册
- POST /login            登录（返回双令牌）
- POST /refresh          刷新令牌
- POST /change-password  修改密码（受保护）
- GET  /me               当前用户信息（受保护）

本层只做参数接收 + 鉴权 + 调用 service + 返回统一格式，不写业务逻辑。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.session import get_db
from db.schemas import UserCreate, UserLogin, PasswordChange
from db.models import User
from api.deps import get_current_user
from utils.response import success_response
from services import auth_service

router = APIRouter()


class RefreshRequest(BaseModel):
    """刷新令牌请求体"""
    refresh_token: str = Field(..., description="刷新令牌")


@router.post("/register")
def register(data: UserCreate, db: Session = Depends(get_db)):
    result = auth_service.register(db, data)
    return success_response(result, "注册成功")


@router.post("/login")
def login(data: UserLogin, db: Session = Depends(get_db)):
    result = auth_service.login(db, data.username, data.password)
    return success_response(result, "登录成功")


@router.post("/refresh")
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    result = auth_service.refresh_token(db, data.refresh_token)
    return success_response(result, "令牌刷新成功")


@router.post("/change-password")
def change_password(
    data: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    auth_service.change_password(db, user.id, data.old_password, data.new_password)
    return success_response(None, "密码修改成功")


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return success_response(auth_service._to_user_dict(user))
