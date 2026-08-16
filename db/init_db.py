"""
数据库初始化脚本

功能：
1. 创建所有数据表
2. 初始化默认管理员账号（admin / Teacher@123）
3. 可选：创建示例知识库与示例用户

使用方式：
    python -m db.init_db
    # 或
    python db/init_db.py
"""
from __future__ import annotations

import sys
import os

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.session import sync_engine, SyncSessionLocal
from db.base import Base
from db import models  # noqa: F401  确保所有模型注册
from db.crud import user_crud
from db.schemas import UserCreate
from config.constants import UserRole
from utils.logger import get_logger

logger = get_logger(__name__)


def create_tables() -> None:
    """创建所有数据表"""
    Base.metadata.create_all(bind=sync_engine)
    logger.info("✅ 数据库表创建完成")


def init_default_admin() -> None:
    """初始化默认管理员账号"""
    db = SyncSessionLocal()
    try:
        existing = user_crud.get_by_username(db, "admin")
        if existing:
            logger.info("ℹ️  管理员账号已存在，跳过创建")
            return

        admin = user_crud.create(
            db,
            UserCreate(
                username="admin",
                password="Teacher@123",
                email="admin@example.com",
                nickname="系统管理员",
                role=UserRole.ADMIN.value,
            ),
        )
        logger.info(f"✅ 默认管理员创建成功: {admin.username} / Teacher@123")
        logger.warning("⚠️  生产环境请立即修改默认密码！")

    finally:
        db.close()


def init_demo_user() -> None:
    """创建演示用户（开发环境用）"""
    db = SyncSessionLocal()
    try:
        existing = user_crud.get_by_username(db, "demo")
        if existing:
            logger.info("ℹ️  演示用户已存在，跳过创建")
            return

        demo = user_crud.create(
            db,
            UserCreate(
                username="demo",
                password="Student@123",
                email="demo@example.com",
                nickname="演示用户",
                role=UserRole.NORMAL.value,
            ),
        )
        logger.info(f"✅ 演示用户创建成功: {demo.username} / Student@123")
    finally:
        db.close()


def init_all() -> None:
    """完整初始化"""
    print("=" * 60)
    print("🚀 课程试卷智能命题校验批改系统 - 数据库初始化")
    print("=" * 60)

    logger.info("开始数据库初始化...")

    # 1. 创建表
    create_tables()

    # 2. 初始化管理员
    init_default_admin()

    # 3. 初始化演示用户
    init_demo_user()

    print("=" * 60)
    print("🎉 数据库初始化完成！")
    print(f"   默认管理员: admin / Teacher@123")
    print(f"   演示用户:   demo / Student@123")
    print("=" * 60)


if __name__ == "__main__":
    init_all()
