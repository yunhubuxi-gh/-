"""
数据库会话管理

支持同步 + 异步两种会话：
- 同步会话：用于大多数 CRUD 操作、后台任务
- 异步会话：用于 FastAPI 异步路由、并发查询

会话采用连接池，通过依赖注入的方式提供给 API 层使用。
"""
from __future__ import annotations

from typing import Generator, AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# 同步数据库引擎与会话
# ============================================================

def _get_sync_db_url() -> str:
    """获取同步数据库连接串"""
    url = settings.database_url
    # SQLite 需要加 check_same_thread=False
    if url.startswith("sqlite"):
        return url
    return url


# 同步引擎
sync_engine = create_engine(
    _get_sync_db_url(),
    echo=settings.debug,  # debug 模式下输出 SQL
    pool_pre_ping=True,    # 连接前检查连接是否有效
    pool_size=10,          # 连接池大小
    max_overflow=20,       # 最大溢出连接数
    pool_recycle=3600,     # 连接回收时间（秒）
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

# 同步会话工厂
SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """
    同步数据库会话依赖（FastAPI Depends 用）。
    使用 yield 保证请求结束后自动关闭会话。
    """
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# 异步数据库引擎与会话
# ============================================================

def _get_async_db_url() -> str:
    """获取异步数据库连接串（自动替换驱动）"""
    url = settings.database_url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")
    elif url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    elif url.startswith("sqlite"):
        return url.replace("sqlite://", "sqlite+aiosqlite://")
    else:
        return url


# 异步引擎（异步操作时才创建，避免强制依赖 asyncpg / aiosqlite）
_async_engine = None
_async_session_factory = None


def _get_async_engine():
    """懒加载异步引擎"""
    global _async_engine, _async_session_factory
    if _async_engine is None:
        try:
            _async_engine = create_async_engine(
                _get_async_db_url(),
                echo=settings.debug,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                pool_recycle=3600,
            )
            _async_session_factory = async_sessionmaker(
                bind=_async_engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
                class_=AsyncSession,
            )
            logger.info("异步数据库引擎初始化完成")
        except ImportError as e:
            raise ImportError(
                "异步数据库驱动未安装。SQLite 请安装 aiosqlite，PostgreSQL 请安装 asyncpg"
            ) from e
    return _async_engine


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    异步数据库会话依赖（FastAPI 异步路由用）。
    """
    _get_async_engine()
    async with _async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


# ============================================================
# 数据库初始化
# ============================================================

def init_db_tables() -> None:
    """
    初始化数据库表（同步方式）。
    启动时调用一次，创建所有表。
    注意：生产环境推荐使用 Alembic 管理迁移。
    """
    from db.base import Base  # noqa: F401
    from db import models  # noqa: F401  确保所有模型都被注册

    Base.metadata.create_all(bind=sync_engine)
    logger.info("数据库表初始化完成")


def drop_db_tables() -> None:
    """删除所有表（测试/重置用，慎用）"""
    from db.base import Base  # noqa: F401
    from db import models  # noqa: F401

    Base.metadata.drop_all(bind=sync_engine)
    logger.warning("数据库表已全部删除！")
