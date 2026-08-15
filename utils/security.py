"""
安全工具模块
- 密码哈希与校验（bcrypt）
- JWT 令牌签发与校验（access token + refresh token 双令牌）
- API 密钥生成
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import jwt

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# ==================== 密码哈希 ====================


def hash_password(password: str) -> str:
    """
    对密码进行 bcrypt 哈希。

    Args:
        password: 明文密码

    Returns:
        哈希后的密码字符串
    """
    try:
        import bcrypt
    except ImportError:
        # fallback: 用 hashlib 实现简单哈希（开发环境兜底，生产请用 bcrypt）
        import hashlib
        import base64
        salt = secrets.token_hex(8)
        digest = hashlib.sha256((password + salt).encode()).hexdigest()
        return f"sha256${salt}${digest}"

    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """
    校验密码是否匹配。

    Args:
        password: 明文密码
        hashed_password: 哈希后的密码

    Returns:
        True 表示匹配
    """
    if not password or not hashed_password:
        return False

    # 兼容 fallback 的 sha256 格式
    if hashed_password.startswith("sha256$"):
        import hashlib
        parts = hashed_password.split("$")
        if len(parts) != 3:
            return False
        _, salt, digest = parts
        return hashlib.sha256((password + salt).encode()).hexdigest() == digest

    try:
        import bcrypt
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ImportError:
        logger.error("bcrypt 未安装，无法校验密码")
        return False


# ==================== JWT 令牌 ====================


def create_access_token(
    subject: str,
    extra_claims: Optional[dict] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    创建访问令牌（Access Token）

    Args:
        subject: 令牌主体（通常是用户 ID）
        extra_claims: 额外声明（如角色、用户名等）
        expires_delta: 过期时间增量，默认取配置

    Returns:
        JWT 字符串
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": "access",
        "iat": now,
        "exp": now + expires_delta,
        "jti": secrets.token_hex(8),  # 令牌唯一标识，用于黑名单
    }
    if extra_claims:
        payload.update(extra_claims)

    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token


def create_refresh_token(
    subject: str,
    extra_claims: Optional[dict] = None,
) -> str:
    """
    创建刷新令牌（Refresh Token），有效期更长。
    """
    expires_delta = timedelta(days=settings.jwt_refresh_token_expire_days)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": "refresh",
        "iat": now,
        "exp": now + expires_delta,
        "jti": secrets.token_hex(8),
    }
    if extra_claims:
        payload.update(extra_claims)

    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return token


def create_token_pair(
    subject: str,
    extra_claims: Optional[dict] = None,
) -> Tuple[str, str]:
    """
    同时创建 access_token 和 refresh_token

    Returns:
        (access_token, refresh_token)
    """
    access = create_access_token(subject, extra_claims)
    refresh = create_refresh_token(subject, extra_claims)
    return access, refresh


def decode_token(token: str, token_type: Optional[str] = None) -> dict:
    """
    解析并校验 JWT 令牌。

    Args:
        token: JWT 字符串
        token_type: 校验令牌类型（access / refresh），None 则不校验

    Returns:
        payload 字典

    Raises:
        jwt.PyJWTError: 令牌无效 / 过期 / 类型不匹配
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise jwt.ExpiredSignatureError("令牌已过期")
    except jwt.InvalidTokenError:
        raise jwt.InvalidTokenError("令牌无效")

    if token_type and payload.get("type") != token_type:
        raise jwt.InvalidTokenError(f"令牌类型不匹配，期望 {token_type}")

    return payload


def decode_access_token(token: str) -> dict:
    """解析访问令牌"""
    return decode_token(token, token_type="access")


def decode_refresh_token(token: str) -> dict:
    """解析刷新令牌"""
    return decode_token(token, token_type="refresh")


# ==================== 通用工具 ====================


def generate_api_key() -> str:
    """生成随机 API Key"""
    return "sk-" + secrets.token_hex(24)


def generate_random_password(length: int = 12) -> str:
    """生成随机密码"""
    import string
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))
