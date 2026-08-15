"""
知识库服务（kb_service）

职责：
- 知识库 CRUD（创建/查询/更新/删除）
- 成员权限管理（添加/更新/移除/列出成员）
- 落地四级权限校验：owner > admin > write > read
    owner：全部权限（含删除知识库）
    admin：管理成员、修改知识库配置
    write：上传/编辑文档（由 document_service 校验）
    read：仅可读问答检索

权限拦截：
- 所有操作先查 kb_crud.get_user_role，再用 utils.permission 校验是否满足所需级别
- 非成员 / 权限不足 -> 抛出 PermissionException（KB_NO_PERMISSION）
- 越权的变更操作写审计日志（result=permission_denied）

依赖：
- db.crud.kb_crud：知识库与成员授权表（不写原生 SQL）
- utils.permission：四级权限校验
- 审计：全部写操作走 services.write_audit_log
"""
from __future__ import annotations

from typing import Dict, Any, Optional

from config.constants import KBUserRole, AuditAction, AuditResult
from db.models import KnowledgeBase
from db.schemas import KBCreate, KBUpdate, KBMemberAdd, KBMemberUpdate
from db.crud import kb_crud, user_crud
from utils.permission import has_permission
from utils.exceptions import (
    ResourceNotFoundException,
    ValidationException,
    PermissionException,
)
from utils.error_codes import (
    KB_NOT_FOUND,
    KB_NO_PERMISSION,
    RESOURCE_NOT_FOUND,
    OPERATION_NOT_ALLOWED,
    PERMISSION_INVALID_ROLE,
)
from utils.response import page_result
from utils.logger import get_logger
from services import write_audit_log

logger = get_logger(__name__)

# 可授予成员的合法角色（owner 不通过成员接口授予）
_VALID_MEMBER_ROLES = (
    KBUserRole.ADMIN.value,
    KBUserRole.WRITE.value,
    KBUserRole.READ.value,
)


class KBService:
    """知识库服务"""

    # ---------- 知识库基本操作 ----------

    def create(self, db, user_id: int, data: KBCreate) -> Dict[str, Any]:
        """创建知识库（创建者自动成为 owner）"""
        kb = kb_crud.create(db, data, user_id)
        write_audit_log(
            db, user_id, AuditAction.KB_CREATE.value,
            resource_type="kb", resource_id=kb.id,
            details={"name": kb.name},
        )
        return self._to_kb_dict(db, kb, user_id)

    def get(self, db, user_id: int, kb_id: int) -> Dict[str, Any]:
        """知识库详情（read+ 可访问）"""
        kb = self._get_kb(db, kb_id)
        self._check_permission(db, kb_id, user_id, KBUserRole.READ, "kb_read", audit_on_deny=False)
        return self._to_kb_dict(db, kb, user_id)

    def list_my(
        self, db, user_id: int, keyword: Optional[str] = None,
        page: int = 1, page_size: int = 20,
    ) -> Dict[str, Any]:
        """列出当前用户有权限的知识库"""
        kbs, total = kb_crud.get_list_by_user(db, user_id, keyword, page, page_size)
        items = [self._to_kb_dict(db, kb, user_id) for kb in kbs]
        return page_result(items, total, page, page_size)

    def update(self, db, user_id: int, kb_id: int, data: KBUpdate) -> Dict[str, Any]:
        """修改知识库配置（admin+）"""
        kb = self._get_kb(db, kb_id)
        self._check_permission(db, kb_id, user_id, KBUserRole.ADMIN, "kb_update",
                               AuditAction.KB_UPDATE.value)
        kb = kb_crud.update(db, kb_id, data)
        write_audit_log(
            db, user_id, AuditAction.KB_UPDATE.value,
            resource_type="kb", resource_id=kb_id,
            details={"name": kb.name if kb else None},
        )
        return self._to_kb_dict(db, kb, user_id)

    def delete(self, db, user_id: int, kb_id: int) -> bool:
        """删除知识库（owner）"""
        kb = self._get_kb(db, kb_id)
        self._check_permission(db, kb_id, user_id, KBUserRole.OWNER, "kb_delete",
                               AuditAction.KB_DELETE.value)
        kb_crud.delete(db, kb_id)
        write_audit_log(
            db, user_id, AuditAction.KB_DELETE.value,
            resource_type="kb", resource_id=kb_id,
            details={"name": kb.name},
        )
        return True

    # ---------- 成员权限管理（admin+）----------

    def list_members(
        self, db, user_id: int, kb_id: int,
        page: int = 1, page_size: int = 50,
    ) -> Dict[str, Any]:
        """列出知识库成员（read+ 可查看）"""
        self._check_permission(db, kb_id, user_id, KBUserRole.READ, "kb_members", audit_on_deny=False)
        members, total = kb_crud.list_members(db, kb_id, page, page_size)
        items = []
        for m in members:
            d = m.to_dict()
            u = user_crud.get_by_id(db, m.user_id)
            if u:
                d["user"] = {
                    "id": u.id,
                    "username": u.username,
                    "nickname": u.nickname,
                    "role": u.role,
                }
            items.append(d)
        return page_result(items, total, page, page_size)

    def add_member(self, db, user_id: int, kb_id: int, data: KBMemberAdd) -> Dict[str, Any]:
        """添加知识库成员（admin+，owner 角色不可授予）"""
        self._check_permission(db, kb_id, user_id, KBUserRole.ADMIN, "kb_member_add",
                               AuditAction.KB_MEMBER_ADD.value)
        self._validate_member_role(data.role)
        if not user_crud.get_by_id(db, data.user_id):
            raise ResourceNotFoundException(RESOURCE_NOT_FOUND, "要添加的用户不存在")

        member = kb_crud.add_member(db, kb_id, data)
        write_audit_log(
            db, user_id, AuditAction.KB_MEMBER_ADD.value,
            resource_type="kb", resource_id=kb_id,
            details={"member_user_id": data.user_id, "role": data.role},
        )
        return member.to_dict()

    def update_member_role(
        self, db, user_id: int, kb_id: int, member_user_id: int, data: KBMemberUpdate,
    ) -> Dict[str, Any]:
        """更新成员权限（admin+，owner 不可被修改）"""
        self._check_permission(db, kb_id, user_id, KBUserRole.ADMIN, "kb_member_update",
                               AuditAction.KB_MEMBER_UPDATE.value)
        self._validate_member_role(data.role)

        member = kb_crud.update_member_role(db, kb_id, member_user_id, data)
        if not member:
            existing_role = kb_crud.get_user_role(db, kb_id, member_user_id)
            if existing_role == KBUserRole.OWNER.value:
                raise ValidationException(OPERATION_NOT_ALLOWED, "不能修改 owner 的权限")
            raise ResourceNotFoundException(RESOURCE_NOT_FOUND, "该用户不是知识库成员")
        write_audit_log(
            db, user_id, AuditAction.KB_MEMBER_UPDATE.value,
            resource_type="kb", resource_id=kb_id,
            details={"member_user_id": member_user_id, "role": data.role},
        )
        return member.to_dict()

    def remove_member(self, db, user_id: int, kb_id: int, member_user_id: int) -> bool:
        """移除成员（admin+，owner 不可移除）"""
        self._check_permission(db, kb_id, user_id, KBUserRole.ADMIN, "kb_member_remove",
                               AuditAction.KB_MEMBER_REMOVE.value)
        ok = kb_crud.remove_member(db, kb_id, member_user_id)
        if not ok:
            existing_role = kb_crud.get_user_role(db, kb_id, member_user_id)
            if existing_role == KBUserRole.OWNER.value:
                raise ValidationException(OPERATION_NOT_ALLOWED, "不能移除 owner")
            raise ResourceNotFoundException(RESOURCE_NOT_FOUND, "该用户不是知识库成员")
        write_audit_log(
            db, user_id, AuditAction.KB_MEMBER_REMOVE.value,
            resource_type="kb", resource_id=kb_id,
            details={"member_user_id": member_user_id},
        )
        return True

    # ---------- 供其他服务/API 层使用的查询 ----------

    def get_user_role(self, db, user_id: int, kb_id: int) -> Optional[str]:
        """查询用户在知识库的角色"""
        return kb_crud.get_user_role(db, kb_id, user_id)

    def has_access(self, db, user_id: int, kb_id: int) -> bool:
        """用户是否有知识库访问权限（至少 read）"""
        return kb_crud.has_access(db, kb_id, user_id)

    # ---------- 内部工具 ----------

    def _get_kb(self, db, kb_id: int) -> KnowledgeBase:
        kb = kb_crud.get_by_id(db, kb_id)
        if not kb:
            raise ResourceNotFoundException(KB_NOT_FOUND, f"知识库 {kb_id} 不存在")
        return kb

    def _check_permission(
        self, db, kb_id: int, user_id: int,
        required_role: KBUserRole, resource: str,
        action: str = AuditAction.KB_UPDATE.value,
        audit_on_deny: bool = True,
    ) -> None:
        """
        知识库权限校验：非成员 / 权限不足 -> PermissionException。
        audit_on_deny=True 时（变更操作）把越权行为写入审计（permission_denied）。
        """
        role = kb_crud.get_user_role(db, kb_id, user_id)
        if role is None:
            if audit_on_deny:
                write_audit_log(
                    db, user_id, action,
                    result=AuditResult.PERMISSION_DENIED.value,
                    resource_type="kb", resource_id=kb_id,
                    details={"op": resource, "user_role": None, "required": required_role.value},
                )
            raise PermissionException(
                KB_NO_PERMISSION, "无该知识库访问权限", {"resource": f"kb_{kb_id}"},
            )
        if not has_permission(role, required_role):
            if audit_on_deny:
                write_audit_log(
                    db, user_id, action,
                    result=AuditResult.PERMISSION_DENIED.value,
                    resource_type="kb", resource_id=kb_id,
                    details={"op": resource, "user_role": role, "required": required_role.value},
                )
            raise PermissionException(
                KB_NO_PERMISSION, f"需要 {required_role.value} 权限", {"resource": f"kb_{kb_id}"},
            )

    @staticmethod
    def _validate_member_role(role: str) -> None:
        if role not in _VALID_MEMBER_ROLES:
            raise ValidationException(
                PERMISSION_INVALID_ROLE,
                f"无效的成员角色 {role}，可选: {list(_VALID_MEMBER_ROLES)}",
            )

    @staticmethod
    def _to_kb_dict(db, kb: KnowledgeBase, user_id: int) -> Dict[str, Any]:
        d = kb.to_dict()
        d["user_role"] = kb_crud.get_user_role(db, kb.id, user_id)
        return d


# 单例
kb_service = KBService()
