"""
权限校验工具
提供知识库权限校验相关的工具函数与装饰器。

权限级别从高到低：
    owner > admin > write > read

高权限级别自动包含低权限级别的访问能力。
"""
from __future__ import annotations

from typing import List

from config.constants import KBUserRole
from utils.exceptions import PermissionException
from utils.error_codes import KB_NO_PERMISSION, PERMISSION_DENIED
from utils.logger import get_logger

logger = get_logger(__name__)


# 权限级别数值映射，用于比较
_ROLE_LEVEL = {
    KBUserRole.OWNER.value: 100,
    KBUserRole.ADMIN.value: 80,
    KBUserRole.WRITE.value: 50,
    KBUserRole.READ.value: 20,
}


def get_role_level(role: str | KBUserRole) -> int:
    """获取权限级别的数值（数值越大权限越高）"""
    role_val = role.value if isinstance(role, KBUserRole) else role
    return _ROLE_LEVEL.get(role_val, 0)


def has_permission(
    user_role: str | KBUserRole,
    required_role: str | KBUserRole,
) -> bool:
    """
    判断用户角色是否满足所需权限。

    Args:
        user_role: 用户当前角色
        required_role: 所需最低角色

    Returns:
        True 表示有权限
    """
    user_level = get_role_level(user_role)
    required_level = get_role_level(required_role)
    return user_level >= required_level


def ensure_permission(
    user_role: str | KBUserRole,
    required_role: str | KBUserRole,
    resource: str = "",
) -> None:
    """
    校验权限，不足则抛出 PermissionException。

    Args:
        user_role: 用户角色
        required_role: 所需最低角色
        resource: 资源标识，用于错误信息

    Raises:
        PermissionException: 权限不足
    """
    if not has_permission(user_role, required_role):
        logger.warning(
            f"权限不足: user_role={user_role}, required={required_role}, resource={resource}"
        )
        raise PermissionException(
            KB_NO_PERMISSION if resource.startswith("kb_") else PERMISSION_DENIED,
            f"权限不足，需要 {required_role} 角色",
            {"resource": resource, "user_role": str(user_role)},
        )


def can_read(user_role: str | KBUserRole) -> bool:
    """是否有读权限"""
    return has_permission(user_role, KBUserRole.READ)


def can_write(user_role: str | KBUserRole) -> bool:
    """是否有写权限（上传/删除文档）"""
    return has_permission(user_role, KBUserRole.WRITE)


def can_manage(user_role: str | KBUserRole) -> bool:
    """是否有管理权限（管理成员、修改知识库设置）"""
    return has_permission(user_role, KBUserRole.ADMIN)


def is_owner(user_role: str | KBUserRole) -> bool:
    """是否是所有者"""
    return has_permission(user_role, KBUserRole.OWNER)


def get_role_hierarchy() -> List[str]:
    """获取权限级别从高到低的角色列表"""
    return [
        KBUserRole.OWNER.value,
        KBUserRole.ADMIN.value,
        KBUserRole.WRITE.value,
        KBUserRole.READ.value,
    ]
