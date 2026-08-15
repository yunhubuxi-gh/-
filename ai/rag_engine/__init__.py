"""
RAG 检索增强生成引擎

子模块划分：
- document_parser: 文档解析（PDF/DOCX/MD/TXT，扫描件 OCR 回退）
- chunker:        语义分块（嵌入相似度边界检测，递归兜底）
- vector_store:   向量数据库封装（Chroma / Milvus 二选一）
- bm25_retriever: BM25 关键词召回（jieba 中文分词）
- reranker:       BGE-Rerank 重排（模型缺失时降级为词重叠打分）
- hybrid_retriever: 多路混合召回（BM25 + 向量 → 加权融合 → 去重）
- hallucination_detector: 幻觉抑制（上下文依赖校验 + 无答案检测）
- citation_formatter: 引用来源标注（文档名 + 页码 + 块编号）
- doc_version_manager: 文档版本管理（重建索引 / 回滚）
- rag_pipeline:   RAG 统一对外入口

存储边界铁则（严格遵守）：
- PostgreSQL 只存业务元数据
- 原始文档二进制 → 文件系统（通过 db 记录的 file_path 读取）
- chunk 文本 + embedding 向量 → 向量库（Chroma / Milvus）
"""
from ai.rag_engine.rag_pipeline import RagPipeline
from ai.rag_engine.hybrid_retriever import RetrievedChunk, HybridRetriever
from ai.rag_engine.document_parser import (
    ParsedDocument,
    PageText,
    parse_document,
)
from ai.rag_engine.chunker import Chunk, SemanticChunker, RecursiveChunker

__all__ = [
    "RagPipeline",
    "RetrievedChunk",
    "HybridRetriever",
    "ParsedDocument",
    "PageText",
    "parse_document",
    "Chunk",
    "SemanticChunker",
    "RecursiveChunker",
]
