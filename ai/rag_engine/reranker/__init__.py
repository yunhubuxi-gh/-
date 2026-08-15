"""
重排（Rerank）子模块

- BgeReranker: 基于 BGE-Rerank 模型（FlagEmbedding）的精排
- OverlapReranker: 词重叠打分（模型缺失时的降级兜底）
- get_reranker(): 工厂，模型可用则用 BGE，否则降级为词重叠

重排目标：对多路融合候选结果按「查询相关性」重新排序，取 top_n。
"""
from ai.rag_engine.reranker.bge_reranker import (
    BaseReranker,
    BgeReranker,
    OverlapReranker,
    get_reranker,
)

__all__ = [
    "BaseReranker",
    "BgeReranker",
    "OverlapReranker",
    "get_reranker",
]
