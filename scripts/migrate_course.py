"""
课程库 / 试卷改造迁移脚本（轻量，保留现有数据）

用途：
1. 给现有 knowledge_bases 表新增 tags（课程标签）列（幂等，已存在则跳过）
2. 通过 Base.metadata.create_all 自动创建新增表（exam_papers / answer_sheets）

背景：本项目未使用 Alembic，新增列需显式 ALTER TABLE（create_all 不会给已存在的表补列）。

运行：
    python -X utf8 scripts/migrate_course.py

幂等：可重复执行，不会破坏现有数据。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from db.session import sync_engine  # noqa: E402
from db.base import Base  # noqa: E402
from db import models  # noqa: E402  F401 确保所有模型注册


def add_tags_column() -> None:
    """给 knowledge_bases 新增 tags 列（幂等）"""
    inspector = inspect(sync_engine)
    existing = [c["name"] for c in inspector.get_columns("knowledge_bases")]
    if "tags" in existing:
        print("  · knowledge_bases.tags 列已存在，跳过")
        return

    # SQLite 无原生 JSON 类型，用 TEXT 存储（SQLAlchemy JSON 列读取时自动 json.loads）
    dialect = sync_engine.dialect.name
    col_type = "JSON" if dialect == "postgresql" else "TEXT"
    with sync_engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE knowledge_bases ADD COLUMN tags {col_type}"))
    print(f"  · 已新增 knowledge_bases.tags 列（{col_type}）")


def create_new_tables() -> None:
    """创建新增表（已有表不动）"""
    before = set(inspect(sync_engine).get_table_names())
    Base.metadata.create_all(bind=sync_engine)
    after = set(inspect(sync_engine).get_table_names())
    created = after - before
    if created:
        print(f"  · 已创建新表: {', '.join(sorted(created))}")
    else:
        print("  · 无新增表（已存在）")


def add_answer_sheet_error_column() -> None:
    """给 answer_sheets 新增 error_message 列（幂等，阶段2答卷批改失败原因）"""
    inspector = inspect(sync_engine)
    tables = inspector.get_table_names()
    if "answer_sheets" not in tables:
        print("  · answer_sheets 表不存在，跳过 error_message 列")
        return
    existing = [c["name"] for c in inspector.get_columns("answer_sheets")]
    if "error_message" in existing:
        print("  · answer_sheets.error_message 列已存在，跳过")
        return
    with sync_engine.begin() as conn:
        conn.execute(text("ALTER TABLE answer_sheets ADD COLUMN error_message TEXT"))
    print("  · 已新增 answer_sheets.error_message 列")


def add_document_warning_column() -> None:
    """给 documents 新增 processing_warning 列（幂等，图片向量化警告信息）"""
    inspector = inspect(sync_engine)
    tables = inspector.get_table_names()
    if "documents" not in tables:
        print("  · documents 表不存在，跳过 processing_warning 列")
        return
    existing = [c["name"] for c in inspector.get_columns("documents")]
    if "processing_warning" in existing:
        print("  · documents.processing_warning 列已存在，跳过")
        return
    with sync_engine.begin() as conn:
        conn.execute(text("ALTER TABLE documents ADD COLUMN processing_warning TEXT"))
    print("  · 已新增 documents.processing_warning 列")


def add_document_progress_column() -> None:
    """给 documents 新增 progress_detail 列（幂等，OCR 等细粒度子阶段进度）"""
    inspector = inspect(sync_engine)
    tables = inspector.get_table_names()
    if "documents" not in tables:
        print("  · documents 表不存在，跳过 progress_detail 列")
        return
    existing = [c["name"] for c in inspector.get_columns("documents")]
    if "progress_detail" in existing:
        print("  · documents.progress_detail 列已存在，跳过")
        return
    dialect = sync_engine.dialect.name
    col_type = "JSON" if dialect == "postgresql" else "TEXT"
    with sync_engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE documents ADD COLUMN progress_detail {col_type}"))
    print(f"  · 已新增 documents.progress_detail 列（{col_type}）")


def main() -> None:
    print("=" * 60)
    print("课程库 / 试卷改造迁移")
    print("=" * 60)
    print("[1/5] 扩展 knowledge_bases 表")
    add_tags_column()
    print("[2/5] 创建新增表")
    create_new_tables()
    print("[3/5] 扩展 answer_sheets 表")
    add_answer_sheet_error_column()
    print("[4/5] 扩展 documents 表（processing_warning）")
    add_document_warning_column()
    print("[5/5] 扩展 documents 表（progress_detail）")
    add_document_progress_column()
    print("=" * 60)
    print("✅ 迁移完成，现有数据已保留")
    print("=" * 60)


if __name__ == "__main__":
    main()
