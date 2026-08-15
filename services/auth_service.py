"""
用户认证服务（auth_service）

职责：
- 注册：用户名/邮箱唯一性校验，密码只存 bcrypt 哈希（绝对禁止明文存储）
- 登录：密码校验（verify_password）+ JWT 双令牌签发 + 登录信息更新
- 令牌刷新：refresh_token 换取新双令牌
- 修改密码：原密码校验通过后写入新密码哈希
- 令牌解析：decode_token + get_current_user（供 API 层依赖注入使用）

依赖：
- db.crud.user_crud：用户表增删改查
- utils.security：密码哈希 / JWT 令牌（不重复实现）
- config.settings：JWT 过期时间等配置（无魔法数字）
- 审计：注册/登录/令牌刷新/改密全部走 services.write_audit_log
"""
from __future__ import annotations

import jwt

from typing import Dict, Any

from config.settings import settings
from config.constants import UserStatus, AuditAction
from db.models import User
from db.schemas import UserCreate
from db.crud import user_crud
from utils.security import (
    verify_password,
    create_token_pair,
    decode_access_token,
    decode_refresh_token,
)
from utils.exceptions import AuthException
from utils.error_codes import (
    AUTH_CREDENTIALS_ERROR,
    AUTH_USER_NOT_FOUND,
    AUTH_USER_DISABLED,
    AUTH_TOKEN_MISSING,
    AUTH_TOKEN_INVALID,
    AUTH_TOKEN_EXPIRED,
    AUTH_REFRESH_TOKEN_INVALID,
    RESOURCE_ALREADY_EXISTS,
)
from utils.logger import get_logger
from services import write_audit_log

logger = get_logger(__name__)


class AuthService:
    """用户认证服务"""

    # ---------- 注册 ----------

    def register(self, db, data: UserCreate, ip: str = "") -> Dict[str, Any]:
        """注册新用户（密码 bcrypt 哈希入库，绝对不存明文）"""
        if user_crud.exists_by_username(db, data.username):
            raise AuthException(RESOURCE_ALREADY_EXISTS, f"用户名 {data.username} 已存在")
        if data.email and user_crud.exists_by_email(db, data.email):
            raise AuthException(RESOURCE_ALREADY_EXISTS, f"邮箱 {data.email} 已注册")

        user = user_crud.create(db, data)
        write_audit_log(
            db, user.id, AuditAction.REGISTER.value,
            resource_type="user", resource_id=user.id,
            details={"username": user.username},
        )
        logger.info(f"注册成功: id={user.id}, username={user.username}")
        return self._to_user_dict(user)

    # ---------- 登录 ----------

    def login(self, db, username: str, password: str, ip: str = "") -> Dict[str, Any]:
        """登录：密码校验 + JWT 双令牌签发 + 登录信息更新"""
        user = user_crud.get_by_username(db, username)
        # 不区分「用户不存在」与「密码错误」，防止账号枚举
        if not user or not verify_password(password, user.password_hash):
            raise AuthException(AUTH_CREDENTIALS_ERROR, "用户名或密码错误")
        if user.status != UserStatus.ACTIVE.value:
            raise AuthException(AUTH_USER_DISABLED, "用户已被禁用")

        user_crud.update_login_info(db, user.id, ip)

        access, refresh = create_token_pair(
            str(user.id),
            {"role": user.role, "username": user.username},
        )
        write_audit_log(
            db, user.id, AuditAction.LOGIN.value,
            resource_type="user", resource_id=user.id,
            details={"username": user.username, "ip": ip},
        )
        logger.info(f"登录成功: id={user.id}, username={user.username}")
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": settings.jwt_access_token_expire_minutes * 60,
            "user": self._to_user_dict(user),
        }

    # ---------- 令牌刷新 ----------

    def refresh_token(self, db, refresh_token: str) -> Dict[str, Any]:
        """用 refresh_token 换取新的双令牌"""
        try:
            payload = decode_refresh_token(refresh_token)
        except jwt.ExpiredSignatureError:
            raise AuthException(AUTH_REFRESH_TOKEN_INVALID, "刷新令牌已过期")
        except jwt.InvalidTokenError:
            raise AuthException(AUTH_REFRESH_TOKEN_INVALID, "刷新令牌无效")

        user_id = payload.get("sub")
        user = user_crud.get_by_id(db, int(user_id)) if user_id else None
        if not user:
            raise AuthException(AUTH_USER_NOT_FOUND, "用户不存在")
        if user.status != UserStatus.ACTIVE.value:
            raise AuthException(AUTH_USER_DISABLED, "用户已被禁用")

        access, refresh = create_token_pair(
            str(user.id),
            {"role": user.role, "username": user.username},
        )
        write_audit_log(
            db, user.id, AuditAction.TOKEN_REFRESH.value,
            resource_type="user", resource_id=user.id,
            details={"username": user.username},
        )
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": settings.jwt_access_token_expire_minutes * 60,
            "user": self._to_user_dict(user),
        }

    # ---------- 修改密码 ----------

    def change_password(self, db, user_id: int, old_password: str, new_password: str) -> bool:
        """修改密码：原密码校验通过后更新为新密码哈希"""
        user = user_crud.get_by_id(db, user_id)
        if not user:
            raise AuthException(AUTH_USER_NOT_FOUND, "用户不存在")
        if not verify_password(old_password, user.password_hash):
            raise AuthException(AUTH_CREDENTIALS_ERROR, "原密码错误")
        user_crud.update_password(db, user_id, new_password)
        write_audit_log(
            db, user_id, AuditAction.USER_UPDATE.value,
            resource_type="user", resource_id=user_id,
            details={"change": "password"},
        )
        return True

    # ---------- 令牌解析 / 当前用户 ----------

    def decode_token(self, token: str) -> dict:
        """解析 access_token（供 API 层校验）"""
        if not token:
            raise AuthException(AUTH_TOKEN_MISSING, "缺少认证令牌")
        try:
            return decode_access_token(token)
        except jwt.ExpiredSignatureError:
            raise AuthException(AUTH_TOKEN_EXPIRED, "认证令牌已过期")
        except jwt.InvalidTokenError:
            raise AuthException(AUTH_TOKEN_INVALID, "认证令牌无效")

    def get_current_user(self, db, token: str) -> User:
        """根据 access_token 获取当前登录用户（校验用户状态）"""
        payload = self.decode_token(token)
        user_id = payload.get("sub")
        user = user_crud.get_by_id(db, int(user_id)) if user_id else None
        if not user:
            raise AuthException(AUTH_USER_NOT_FOUND, "用户不存在")
        if user.status != UserStatus.ACTIVE.value:
            raise AuthException(AUTH_USER_DISABLED, "用户已被禁用")
        return user

    # ---------- 序列化 ----------

    @staticmethod
    def _to_user_dict(user: User) -> Dict[str, Any]:
        """用户信息出参（绝不返回 password_hash）"""
        d = user.to_dict()
        d.pop("password_hash", None)
        return d


# 单例
auth_service = AuthService()
