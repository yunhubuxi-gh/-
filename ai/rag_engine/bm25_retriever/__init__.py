"""
BM25 关键词召回子模块

基于 BM25 算法的关键词召回，配合 jieba 中文分词。
与向量召回互补：BM25 擅长精确关键词/专有名词匹配。
按知识库（collection）维护独立索引，支持持久化到本地磁盘。
"""
from ai.rag_engine.bm25_retriever.bm25_engine import (
    BM25Engine,
    BM25Hit,
    get_bm25_engine,
    reset_bm25_engine,
)

__all__ = ["BM25Engine", "BM25Hit", "get_bm25_engine", "reset_bm25_engine"]
