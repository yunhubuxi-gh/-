"""
【外部业务工具】CSV 导出工具

将结构化数据（list[dict]）导出为 CSV 文件，写入导出目录。
用于 Agent 把检索/统计结果导出为文件。
"""
from __future__ import annotations

import csv
import os
import time
from typing import List, Dict, Any
from pydantic import BaseModel, Field

from ai.agent_langgraph.tools.base_tool import BaseTool, ToolCategory
from config.settings import settings
from utils.file_utils import ensure_dir, sanitize_filename
from utils.logger import get_logger

logger = get_logger(__name__)


class ExportCsvInput(BaseModel):
    """CSV 导出工具输入"""
    data: List[Dict[str, Any]] = Field(..., description="要导出的数据（字典列表）")
    filename: str = Field("export.csv", description="导出文件名（不含目录）")


class ExportCsvOutput(BaseModel):
    """CSV 导出工具输出"""
    file_path: str = Field(description="导出的 CSV 文件绝对路径")
    row_count: int = Field(description="导出的数据行数")


class ExportCsvTool(BaseTool):
    """CSV 导出工具（外部业务工具）"""

    name = "export_csv"
    display_name = "导出CSV"
    category = ToolCategory.EXTERNAL_BIZ
    description = (
        "将结构化数据（字典列表）导出为 CSV 文件。当需要把检索结果、"
        "统计汇总等数据生成可下载的表格文件时使用。"
    )

    args_schema = ExportCsvInput
    result_schema = ExportCsvOutput

    def __init__(self, export_dir: str | None = None):
        self._export_dir = export_dir or settings.export_dir

    def _execute(self, input_data: ExportCsvInput) -> ExportCsvOutput:
        data = input_data.data
        if not data:
            return ExportCsvOutput(file_path="", row_count=0)

        ensure_dir(self._export_dir)
        safe_name = sanitize_filename(input_data.filename)
        if not safe_name.endswith(".csv"):
            safe_name += ".csv"
        # 加时间戳避免覆盖
        name, ext = os.path.splitext(safe_name)
        file_path = os.path.join(self._export_dir, f"{name}_{int(time.time())}{ext}")

        # 表头取所有键的并集（保持顺序稳定）
        headers: List[str] = []
        for row in data:
            for k in row.keys():
                if k not in headers:
                    headers.append(k)

        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in data:
                writer.writerow(row)

        logger.info(f"CSV 导出完成: {file_path}, rows={len(data)}")
        return ExportCsvOutput(file_path=file_path, row_count=len(data))
