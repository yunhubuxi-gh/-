"""
【内部 RAG 检索工具】知识库搜索工具
Agent 的核心内部工具，用于从私有知识库中检索相关文档片段。
属于"内部工具"分类：只依赖企业内部知识库，不调用外部业务系统。
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from ai.agent_langgraph.tools.base_tool import BaseTool, ToolCategory
from ai.rag_engine.rag_pipeline import RagPipeline
from utils.logger import get_logger

logger = get_logger(__name__)


class KBSearchInput(BaseModel):
    """知识库搜索工具输入参数"""
    query: str = Field(..., description="要搜索的问题或关键词")
    knowledge_base_id: Optional[str] = Field(
        None, description="指定知识库ID，不填则在所有授权知识库中搜索"
    )
    top_k: int = Field(5, description="返回最相关的文档块数量", ge=1, le=20)


class KBSearchOutput(BaseModel):
    """知识库搜索工具输出"""
    results: List[Dict[str, Any]] = Field(description="搜索结果列表")
    total: int = Field(description="结果总数")


class KBSearchTool(BaseTool):
    """
    知识库搜索工具（内部 RAG 检索工具）

    工具定位：
    - 分类：内部 RAG 检索工具（Internal）
    - 作用：从企业私有知识库中检索与查询相关的文档片段
    - 使用场景：Agent 在需要基于内部文档回答问题、查找资料时调用

    特点：
    - 调用 RAG Pipeline 的混合召回（BM25 + 向量 + 重排）
    - 返回结果包含原文、来源文档、页码等引用信息
    """

    name = "kb_search"
    display_name = "知识库搜索"
    category = ToolCategory.INTERNAL_RAG
    description = (
        "从企业私有知识库中搜索与问题相关的文档片段。"
        "当需要基于内部文档、制度、手册、报告等资料回答问题、"
        "查找具体信息、获取文档原文时，使用此工具。"
        "输入搜索关键词或问题，返回相关文档片段及来源引用。"
    )

    args_schema = KBSearchInput
    result_schema = KBSearchOutput

    def __init__(self, rag_pipeline: Optional[RagPipeline] = None):
        self._rag_pipeline = rag_pipeline or RagPipeline()

    def _execute(self, input_data: KBSearchInput) -> KBSearchOutput:
        """
        执行知识库搜索

        Args:
            input_data: 搜索参数

        Returns:
            搜索结果（含文档内容、来源、页码、相似度分数）
        """
        logger.info(
            f"Agent调用知识库搜索工具: query={input_data.query[:50]}..., "
            f"kb_id={input_data.knowledge_base_id}, top_k={input_data.top_k}"
        )

        try:
            # 调用 RAG 混合召回
            retrieved_docs = self._rag_pipeline.retrieve(
                query=input_data.query,
                knowledge_base_ids=[input_data.knowledge_base_id]
                if input_data.knowledge_base_id
                else None,
                top_k=input_data.top_k,
            )

            results = []
            for doc in retrieved_docs:
                results.append({
                    "content": doc.content,
                    "document_id": doc.document_id,
                    "document_name": doc.metadata.get("document_name", ""),
                    "knowledge_base_id": doc.knowledge_base_id,
                    "page_number": doc.page_number,
                    "score": doc.score,
                    "chunk_id": doc.chunk_id,
                })

            logger.info(f"知识库搜索返回 {len(results)} 条结果")
            return KBSearchOutput(results=results, total=len(results))

        except Exception as e:
            logger.error(f"知识库搜索工具执行失败: {str(e)}")
            raise RuntimeError(f"知识库搜索失败: {str(e)}") from e
