"""
BM25 关键词召回引擎

- 中文分词使用 jieba（text_utils.tokenize_for_bm25）
- 优先使用 rank_bm25 的 BM25Okapi；未安装时降级为内置纯 Python BM25
- 按知识库（collection_name）维护独立索引，支持磁盘持久化

索引结构：{collection_name: {"chunks": [ChunkRecord], "bm25": 序列化后的模型}}
"""
from __future__ import annotations

import math
import os
import pickle
from typing import List, Dict, Optional

from ai.rag_engine.chunker.base_chunker import Chunk
from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class BM25Hit:
    """BM25 召回结果"""
    __slots__ = ("chunk_id", "document_id", "content", "page_number",
                 "chunk_index", "score", "metadata")

    def __init__(self, chunk_id, document_id, content, page_number,
                 chunk_index, score, metadata):
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.content = content
        self.page_number = page_number
        self.chunk_index = chunk_index
        self.score = score
        self.metadata = metadata or {}

    def __repr__(self) -> str:
        return f"BM25Hit(chunk_id={self.chunk_id}, score={self.score:.4f})"


class _SimpleBM25:
    """
    纯 Python BM25 实现（rank_bm25 缺失时的兜底）
    标准公式：score = IDF(q) * (f(q,D) * (k1+1)) / (f(q,D) + k1 * (1 - b + b*|D|/avgdl))
    """

    def __init__(self, corpus_tokens: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = corpus_tokens
        self.n = len(corpus_tokens)
        self.avgdl = sum(len(d) for d in corpus_tokens) / self.n if self.n else 1.0
        self.doc_freq: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.doc_len = [len(d) for d in corpus_tokens]
        self._build()

    def _build(self):
        for tokens in self.corpus:
            for term in set(tokens):
                self.doc_freq[term] = self.doc_freq.get(term, 0) + 1
        for term, freq in self.doc_freq.items():
            self.idf[term] = math.log((self.n - freq + 0.5) / (freq + 0.5) + 1.0)

    def get_scores(self, query_tokens: List[str]) -> List[float]:
        scores = [0.0] * self.n
        for term in query_tokens:
            if term not in self.idf:
                continue
            idf = self.idf[term]
            for i, doc in enumerate(self.corpus):
                f = doc.count(term)
                if f == 0:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                scores[i] += idf * (f * (self.k1 + 1)) / denom
        return scores


class BM25Engine:
    """
    BM25 关键词召回引擎（按知识库独立索引）
    """

    def __init__(self, index_dir: str | None = None):
        self._index_dir = index_dir or settings.bm25_index_dir
        # collection_name -> {"chunks": List[dict], "tokens": List[List[str]], "model": ...}
        self._indexes: Dict[str, dict] = {}
        self._tokenize = self._build_tokenizer()

    # ---------- 分词 ----------

    @staticmethod
    def _build_tokenizer():
        try:
            from utils.text_utils import tokenize_for_bm25
            def _tok(text: str) -> List[str]:
                return tokenize_for_bm25(text).split()
            return _tok
        except Exception:
            def _fallback(text: str) -> List[str]:
                return list(text.lower())
            return _fallback

    # ---------- 索引维护 ----------

    def add_documents(self, collection_name: str, chunks: List[Chunk]) -> None:
        """向指定知识库索引追加文档块"""
        index = self._indexes.setdefault(collection_name, {"chunks": [], "tokens": [], "model": None})
        for chunk in chunks:
            index["chunks"].append({
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "content": chunk.text,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "metadata": chunk.metadata,
            })
            index["tokens"].append(self._tokenize(chunk.text))
        self._rebuild_model(collection_name)

    def remove_documents(self, collection_name: str, document_ids: List[str]) -> None:
        """从索引移除指定文档的所有块"""
        if collection_name not in self._indexes:
            return
        index = self._indexes[collection_name]
        doc_set = set(str(d) for d in document_ids)
        kept_chunks, kept_tokens = [], []
        for c, t in zip(index["chunks"], index["tokens"]):
            if c["document_id"] in doc_set:
                continue
            kept_chunks.append(c)
            kept_tokens.append(t)
        index["chunks"] = kept_chunks
        index["tokens"] = kept_tokens
        self._rebuild_model(collection_name)

    def _rebuild_model(self, collection_name: str) -> None:
        index = self._indexes[collection_name]
        tokens = index["tokens"]
        if not tokens:
            index["model"] = None
            return
        try:
            from rank_bm25 import BM25Okapi
            index["model"] = BM25Okapi(tokens)
        except ImportError:
            index["model"] = _SimpleBM25(tokens)

    # ---------- 检索 ----------

    def search(self, collection_name: str, query: str, top_k: int = 10) -> List[BM25Hit]:
        """BM25 关键词召回"""
        index = self._indexes.get(collection_name)
        if not index or not index.get("model") or not index.get("chunks"):
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = index["model"].get_scores(query_tokens)

        # 取 top_k
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        hits: List[BM25Hit] = []
        for i, score in ranked:
            if score <= 0:
                continue
            c = index["chunks"][i]
            hits.append(BM25Hit(
                chunk_id=c["chunk_id"],
                document_id=c["document_id"],
                content=c["content"],
                page_number=c.get("page_number"),
                chunk_index=c.get("chunk_index", 0),
                score=float(score),
                metadata=c.get("metadata", {}),
            ))
        return hits

    def count(self, collection_name: str) -> int:
        index = self._indexes.get(collection_name)
        return len(index["chunks"]) if index else 0

    # ---------- 持久化 ----------

    def save(self, collection_name: Optional[str] = None) -> None:
        """持久化索引到磁盘（默认保存全部）"""
        os.makedirs(self._index_dir, exist_ok=True)
        names = [collection_name] if collection_name else list(self._indexes.keys())
        for name in names:
            if name not in self._indexes:
                continue
            payload = {
                "chunks": self._indexes[name]["chunks"],
                "tokens": self._indexes[name]["tokens"],
            }
            path = self._index_path(name)
            with open(path, "wb") as f:
                pickle.dump(payload, f)
            logger.debug(f"BM25 索引已保存: {name} -> {path}")

    def load(self, collection_name: str) -> bool:
        """从磁盘加载索引"""
        path = self._index_path(collection_name)
        if not os.path.exists(path):
            return False
        try:
            with open(path, "rb") as f:
                payload = pickle.load(f)
            self._indexes[collection_name] = {
                "chunks": payload["chunks"],
                "tokens": payload["tokens"],
                "model": None,
            }
            self._rebuild_model(collection_name)
            return True
        except Exception as e:
            logger.warning(f"加载 BM25 索引失败: {collection_name}, {e}")
            return False

    def _index_path(self, collection_name: str) -> str:
        safe = "".join(c for c in collection_name if c.isalnum() or c in "-_")
        return os.path.join(self._index_dir, f"{safe}.pkl")


# 全局单例
_bm25_engine: Optional[BM25Engine] = None


def get_bm25_engine() -> BM25Engine:
    """获取 BM25 引擎单例"""
    global _bm25_engine
    if _bm25_engine is None:
        _bm25_engine = BM25Engine()
    return _bm25_engine


def reset_bm25_engine() -> None:
    """重置 BM25 引擎（测试用）"""
    global _bm25_engine
    _bm25_engine = None
