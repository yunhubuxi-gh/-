"""
Agent 工具集

分为两类：
1. INTERNAL_RAG  — 内部 RAG 检索工具（知识库搜索，调用 rag_engine）
2. EXTERNAL_BIZ  — 外部业务工具（文档摘要、CSV 导出）

统一由 ToolRegistry 管理，供规划节点 / 执行节点调度。
"""
from ai.agent_langgraph.tools.base_tool import BaseTool, ToolCategory
from ai.agent_langgraph.tools.registry import ToolRegistry, build_default_registry

__all__ = [
    "BaseTool",
    "ToolCategory",
    "ToolRegistry",
    "build_default_registry",
]
