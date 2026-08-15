"""
ORM 模型基类
所有数据表模型都继承自此基类，自动包含公共字段：
- id: 主键（自增整数）
- created_at: 创建时间
- updated_at: 更新时间
- is_deleted: 软删除标记
"""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, Integer, DateTime, Boolean, func
from sqlalchemy.orm import declarative_base

# 声明式基类
Base = declarative_base()


class BaseModel(Base):
    """
    模型基类，所有业务表继承此类。
    包含公共字段：id、created_at、updated_at、is_deleted
    """
    __abstract__ = True

    id = Column(Integer, primary_key=True, autoincrement=True, index=True, comment="主键ID")

    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )

    is_deleted = Column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="软删除标记",
    )

    def to_dict(self) -> dict:
        """转换为字典（排除软删除字段，避免返回给前端）"""
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data.pop("is_deleted", None)
        # datetime 转字符串
        for k, v in data.items():
            if isinstance(v, datetime):
                data[k] = v.isoformat()
        return data
