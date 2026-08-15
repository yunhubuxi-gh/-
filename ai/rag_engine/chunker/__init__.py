"""
文档分块子模块

- SemanticChunker: 语义分块（基于嵌入相似度的边界检测，主策略）
- RecursiveChunker: 递归字符分块（兜底策略，无嵌入模型时使用）

分块结果 Chunk 携带文档 id、页码、块序号，用于引用溯源。
"""
from ai.rag_engine.chunker.base_chunker import Chunk, BaseChunker
from ai.rag_engine.chunker.recursive_chunker import RecursiveChunker
from ai.rag_engine.chunker.semantic_chunker import SemanticChunker

__all__ = [
    "Chunk",
    "BaseChunker",
    "RecursiveChunker",
    "SemanticChunker",
]
