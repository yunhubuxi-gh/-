"""
工具注册表

统一管理 Agent 可用的全部工具，按 name 索引。
提供默认工具集的构建（内部 RAG 检索工具 + 外部业务工具）。
"""
from __future__ import annotations

from typing import List, Dict, Optional

from ai.agent_langgraph.tools.base_tool import BaseTool
from utils.logger import get_logger

logger = get_logger(__name__)


class ToolRegistry:
    """工具注册表（name -> 工具实例）"""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """注册一个工具"""
        if not tool.name:
            raise ValueError("工具缺少 name")
        self._tools[tool.name] = tool
        logger.debug(f"注册工具: {tool.name}")

    def get(self, name: str) -> Optional[BaseTool]:
        """按名称获取工具"""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> List[BaseTool]:
        return list(self._tools.values())

    def list_tool_names(self) -> List[str]:
        return list(self._tools.keys())

    def list_tool_infos(self) -> List[dict]:
        """工具元信息列表（供规划提示词使用）"""
        return [t.get_tool_info() for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)


def build_default_registry(
    rag_pipeline=None,
    llm_client=None,
    export_dir: Optional[str] = None,
) -> ToolRegistry:
    """
    构建默认工具集：
    - kb_search（内部 RAG 检索工具，调用 rag_engine 统一入口）
    - doc_summary（外部：文档摘要）
    - export_csv（外部：CSV 导出）
    """
    from ai.agent_langgraph.tools.internal.kb_search_tool import KBSearchTool
    from ai.agent_langgraph.tools.external.doc_summary_tool import DocSummaryTool
    from ai.agent_langgraph.tools.external.export_csv_tool import ExportCsvTool

    registry = ToolRegistry()
    registry.register(KBSearchTool(rag_pipeline=rag_pipeline))
    registry.register(DocSummaryTool(llm_client=llm_client))
    registry.register(ExportCsvTool(export_dir=export_dir))
    logger.info(f"默认工具集构建完成: {registry.list_tool_names()}")
    return registry
