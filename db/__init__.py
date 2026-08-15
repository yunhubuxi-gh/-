"""
db 数据库层

只存储业务元数据，遵守三者分离原则：
- PostgreSQL:  业务元数据（用户/知识库/文档/会话/Agent任务/审计日志）
- 向量数据库:  文档嵌入向量
- 文件系统:    原始文档二进制文件

子模块:
- base:      ORM 模型基类
- models:    全部 ORM 模型定义
- schemas:   Pydantic 请求/响应 DTO
- session:   数据库会话管理
- crud:      数据访问层（业务层通过 CRUD 操作数据库，不直接写 SQL）
- init_db:   数据库初始化脚本
"""
from db.base import Base
from db.session import get_db, get_async_db, init_db_tables
from db.models import *  # noqa: F401,F403

__all__ = [
    "Base",
    "get_db",
    "get_async_db",
    "init_db_tables",
]
