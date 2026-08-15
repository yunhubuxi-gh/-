"""
用户 CRUD
"""
from __future__ import annotations

from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from pydantic import BaseModel as PydanticBaseModel
from db.models import User
from db.schemas import UserCreate, UserUpdate
from utils.security import hash_password
from utils.logger import get_logger

logger = get_logger(__name__)


class UserCRUD:
    """用户 CRUD 封装类"""

    model = User

    # ---------- 查询 ----------

    def get_by_id(self, db: Session, user_id: int) -> Optional[User]:
        """根据 ID 获取用户（排除已删除）"""
        return db.query(User).filter(
            User.id == user_id,
            User.is_deleted == False,  # noqa: E712
        ).first()

    def get_by_username(self, db: Session, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        return db.query(User).filter(
            User.username == username,
            User.is_deleted == False,  # noqa: E712
        ).first()

    def get_by_email(self, db: Session, email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        if not email:
            return None
        return db.query(User).filter(
            User.email == email,
            User.is_deleted == False,  # noqa: E712
        ).first()

    def get_list(
        self,
        db: Session,
        keyword: Optional[str] = None,
        role: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[User], int]:
        """
        分页获取用户列表

        Returns:
            (用户列表, 总数)
        """
        query = db.query(User).filter(User.is_deleted == False)  # noqa: E712

        if keyword:
            like = f"%{keyword}%"
            query = query.filter(or_(User.username.like(like), User.nickname.like(like)))
        if role:
            query = query.filter(User.role == role)
        if status:
            query = query.filter(User.status == status)

        total = query.count()
        users = query.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return users, total

    # ---------- 创建 ----------

    def create(self, db: Session, obj_in: UserCreate) -> User:
        """
        创建新用户

        Args:
            db: 数据库会话
            obj_in: 用户创建参数

        Returns:
            创建后的用户对象
        """
        user_data = obj_in.model_dump(exclude={"password"})
        # 密码只存哈希
        user_data["password_hash"] = hash_password(obj_in.password)
        db_user = User(**user_data)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        logger.info(f"创建用户: id={db_user.id}, username={db_user.username}")
        return db_user

    # ---------- 更新 ----------

    def update(self, db: Session, user_id: int, obj_in: UserUpdate | dict) -> Optional[User]:
        """更新用户信息"""
        user = self.get_by_id(db, user_id)
        if not user:
            return None

        update_data = obj_in.model_dump(exclude_unset=True) if isinstance(obj_in, PydanticBaseModel) else obj_in

        for field, value in update_data.items():
            if hasattr(user, field) and value is not None:
                setattr(user, field, value)

        db.commit()
        db.refresh(user)
        logger.info(f"更新用户: id={user_id}")
        return user

    def update_password(self, db: Session, user_id: int, new_password: str) -> Optional[User]:
        """更新密码"""
        user = self.get_by_id(db, user_id)
        if not user:
            return None
        user.password_hash = hash_password(new_password)
        db.commit()
        db.refresh(user)
        logger.info(f"更新密码: user_id={user_id}")
        return user

    def update_login_info(self, db: Session, user_id: int, ip: str = "") -> Optional[User]:
        """更新登录信息（登录次数、时间、IP）"""
        from datetime import datetime
        user = self.get_by_id(db, user_id)
        if not user:
            return None
        user.login_count = (user.login_count or 0) + 1
        user.last_login_at = datetime.utcnow()
        user.last_login_ip = ip
        db.commit()
        return user

    # ---------- 删除 ----------

    def delete(self, db: Session, user_id: int) -> bool:
        """软删除用户"""
        user = self.get_by_id(db, user_id)
        if not user:
            return False
        user.is_deleted = True
        db.commit()
        logger.info(f"删除用户: id={user_id}")
        return True

    # ---------- 存在性检查 ----------

    def exists_by_username(self, db: Session, username: str) -> bool:
        """用户名是否已存在"""
        return self.get_by_username(db, username) is not None

    def exists_by_email(self, db: Session, email: str) -> bool:
        """邮箱是否已存在"""
        if not email:
            return False
        return self.get_by_email(db, email) is not None


# 单例
user_crud = UserCRUD()
