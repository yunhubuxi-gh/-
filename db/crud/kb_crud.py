"""
知识库 CRUD + 权限管理
"""
from __future__ import annotations

from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from db.models import KnowledgeBase, KnowledgeBaseUser, User
from db.schemas import KBCreate, KBUpdate, KBMemberAdd, KBMemberUpdate
from config.constants import KBUserRole, KBStatus
from utils.logger import get_logger

logger = get_logger(__name__)


class KBCRUD:
    """知识库 CRUD 封装类"""

    model = KnowledgeBase

    # ---------- 知识库基本操作 ----------

    def get_by_id(self, db: Session, kb_id: int) -> Optional[KnowledgeBase]:
        """根据 ID 获取知识库"""
        return db.query(KnowledgeBase).filter(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.is_deleted == False,  # noqa: E712
        ).first()

    def get_list_by_user(
        self,
        db: Session,
        user_id: int,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[KnowledgeBase], int]:
        """
        获取用户有权限的知识库列表

        通过 knowledge_base_users 关联表过滤。
        """
        query = db.query(KnowledgeBase).join(
            KnowledgeBaseUser,
            KnowledgeBase.id == KnowledgeBaseUser.knowledge_base_id
        ).filter(
            KnowledgeBaseUser.user_id == user_id,
            KnowledgeBase.is_deleted == False,  # noqa: E712
        )

        if keyword:
            query = query.filter(KnowledgeBase.name.like(f"%{keyword}%"))

        total = query.count()
        kbs = query.order_by(KnowledgeBase.updated_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        return kbs, total

    def create(self, db: Session, obj_in: KBCreate, owner_id: int) -> KnowledgeBase:
        """
        创建知识库。
        创建者自动成为 owner。
        """
        kb_data = obj_in.model_dump()
        kb_data["owner_id"] = owner_id
        kb = KnowledgeBase(**kb_data)
        db.add(kb)
        db.flush()  # 先拿到 id

        # 向量库集合名称：kb_{id}
        kb.vector_collection = f"kb_{kb.id}"

        # 创建者作为 owner 加入授权表
        member = KnowledgeBaseUser(
            knowledge_base_id=kb.id,
            user_id=owner_id,
            role=KBUserRole.OWNER.value,
        )
        db.add(member)

        db.commit()
        db.refresh(kb)
        logger.info(f"创建知识库: id={kb.id}, name={kb.name}, owner_id={owner_id}")
        return kb

    def update(self, db: Session, kb_id: int, obj_in: KBUpdate | dict) -> Optional[KnowledgeBase]:
        """更新知识库"""
        kb = self.get_by_id(db, kb_id)
        if not kb:
            return None

        update_data = obj_in.model_dump(exclude_unset=True) if hasattr(obj_in, "model_dump") else obj_in
        for field, value in update_data.items():
            if hasattr(kb, field) and value is not None:
                setattr(kb, field, value)

        db.commit()
        db.refresh(kb)
        logger.info(f"更新知识库: id={kb_id}")
        return kb

    def delete(self, db: Session, kb_id: int) -> bool:
        """软删除知识库"""
        kb = self.get_by_id(db, kb_id)
        if not kb:
            return False
        kb.is_deleted = True
        kb.status = KBStatus.ARCHIVED.value
        db.commit()
        logger.info(f"删除知识库: id={kb_id}")
        return True

    def update_stats(self, db: Session, kb_id: int, doc_delta: int = 0, chunk_delta: int = 0) -> None:
        """更新知识库统计数（原子增减）"""
        kb = self.get_by_id(db, kb_id)
        if not kb:
            return
        kb.doc_count = max(0, (kb.doc_count or 0) + doc_delta)
        kb.chunk_count = max(0, (kb.chunk_count or 0) + chunk_delta)
        db.commit()

    # ---------- 权限相关 ----------

    def get_user_role(self, db: Session, kb_id: int, user_id: int) -> Optional[str]:
        """获取用户在知识库中的角色"""
        member = db.query(KnowledgeBaseUser).filter(
            KnowledgeBaseUser.knowledge_base_id == kb_id,
            KnowledgeBaseUser.user_id == user_id,
            KnowledgeBaseUser.is_deleted == False,  # noqa: E712
        ).first()
        return member.role if member else None

    def has_access(self, db: Session, kb_id: int, user_id: int) -> bool:
        """用户是否有该知识库的访问权限（至少是 read）"""
        return self.get_user_role(db, kb_id, user_id) is not None

    def check_user_role(
        self,
        db: Session,
        kb_id: int,
        user_id: int,
        required_role: str | KBUserRole,
    ) -> bool:
        """检查用户是否满足指定权限级别"""
        from utils.permission import has_permission
        role = self.get_user_role(db, kb_id, user_id)
        if not role:
            return False
        return has_permission(role, required_role)

    # ---------- 成员管理 ----------

    def add_member(self, db: Session, kb_id: int, obj_in: KBMemberAdd) -> Optional[KnowledgeBaseUser]:
        """添加知识库成员"""
        # 检查是否已存在
        existing = db.query(KnowledgeBaseUser).filter(
            KnowledgeBaseUser.knowledge_base_id == kb_id,
            KnowledgeBaseUser.user_id == obj_in.user_id,
            KnowledgeBaseUser.is_deleted == False,  # noqa: E712
        ).first()
        if existing:
            # 已存在则更新角色
            existing.role = obj_in.role
            db.commit()
            db.refresh(existing)
            return existing

        member = KnowledgeBaseUser(
            knowledge_base_id=kb_id,
            user_id=obj_in.user_id,
            role=obj_in.role,
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        logger.info(f"添加知识库成员: kb_id={kb_id}, user_id={obj_in.user_id}, role={obj_in.role}")
        return member

    def update_member_role(
        self, db: Session, kb_id: int, user_id: int, obj_in: KBMemberUpdate
    ) -> Optional[KnowledgeBaseUser]:
        """更新成员权限"""
        member = db.query(KnowledgeBaseUser).filter(
            KnowledgeBaseUser.knowledge_base_id == kb_id,
            KnowledgeBaseUser.user_id == user_id,
            KnowledgeBaseUser.is_deleted == False,  # noqa: E712
        ).first()
        if not member:
            return None
        # 不能更改 owner 角色
        from utils.permission import is_owner
        if is_owner(member.role):
            return None
        member.role = obj_in.role
        db.commit()
        db.refresh(member)
        logger.info(f"更新成员权限: kb_id={kb_id}, user_id={user_id}, role={obj_in.role}")
        return member

    def remove_member(self, db: Session, kb_id: int, user_id: int) -> bool:
        """移除知识库成员（软删除）"""
        member = db.query(KnowledgeBaseUser).filter(
            KnowledgeBaseUser.knowledge_base_id == kb_id,
            KnowledgeBaseUser.user_id == user_id,
            KnowledgeBaseUser.is_deleted == False,  # noqa: E712
        ).first()
        if not member:
            return False
        # owner 不能被移除
        from utils.permission import is_owner
        if is_owner(member.role):
            return False
        member.is_deleted = True
        db.commit()
        logger.info(f"移除知识库成员: kb_id={kb_id}, user_id={user_id}")
        return True

    def list_members(
        self,
        db: Session,
        kb_id: int,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[KnowledgeBaseUser], int]:
        """列出知识库所有成员"""
        query = db.query(KnowledgeBaseUser).filter(
            KnowledgeBaseUser.knowledge_base_id == kb_id,
            KnowledgeBaseUser.is_deleted == False,  # noqa: E712
        )
        total = query.count()
        members = query.order_by(KnowledgeBaseUser.role.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        return members, total


# 单例
kb_crud = KBCRUD()
