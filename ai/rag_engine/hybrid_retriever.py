"""
多路混合召回器

召回策略：
1. BM25 关键词召回（精确关键词 / 专有名词）
2. 向量语义召回（语义相似）
3. 加权融合（分数归一化 + 权重配置化，默认 BM25:0.3 / 向量:0.7）
4. 按 chunk_id 去重（同一块出现在两路时合并分数）
5. BGE-Rerank 精排，取 top_k

对外返回统一的 RetrievedChunk 结构（含引用溯源所需元数据）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# 融合权重（可通过环境变量覆盖，此处用 getattr 保持与 settings 解耦）
BM25_WEIGHT = getattr(settings, "bm25_weight", 0.3)
VECTOR_WEIGHT = getattr(settings, "vector_weight", 0.7)


@dataclass
class RetrievedChunk:
    """检索结果统一结构（供 RAG 生成与引用标注使用）"""
    chunk_id: str
    document_id: str
    knowledge_base_id: str
    content: str
    score: float
    page_number: Optional[int] = None
    chunk_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def document_name(self) -> str:
        return self.metadata.get("document_name", "") or self.metadata.get("document_title", "")

    def __repr__(self) -> str:
        return (
            f"RetrievedChunk(chunk_id={self.chunk_id}, doc={self.document_id}, "
            f"score={self.score:.4f}, page={self.page_number})"
        )


class HybridRetriever:
    """
    多路混合召回器（BM25 + 向量 → 融合 → 重排）
    """

    def __init__(self, vector_store=None, bm25_engine=None, embedding_client=None, reranker=None):
        """
        Args:
            vector_store: 向量库实例（缺省用工厂 get_vector_store）
            bm25_engine: BM25 引擎（缺省用 get_bm25_engine）
            embedding_client: 嵌入客户端（需 embed_query），缺省用 get_embedding_client
            reranker: 重排器（缺省用 get_reranker）
        """
        self.vector_store = vector_store
        self.bm25_engine = bm25_engine
        self.embedding_client = embedding_client
        self.reranker = reranker
        self.bm25_weight = BM25_WEIGHT
        self.vector_weight = VECTOR_WEIGHT

    # ---------- 懒加载依赖 ----------

    def _get_vector_store(self):
        if self.vector_store is None:
            from ai.rag_engine.vector_store import get_vector_store
            self.vector_store = get_vector_store()
        return self.vector_store

    def _get_bm25(self):
        if self.bm25_engine is None:
            from ai.rag_engine.bm25_retriever import get_bm25_engine
            self.bm25_engine = get_bm25_engine()
        return self.bm25_engine

    def _get_embedding(self):
        if self.embedding_client is None:
            from utils.embedding_client import get_embedding_client
            self.embedding_client = get_embedding_client()
        return self.embedding_client

    def _get_reranker(self):
        if self.reranker is None:
            from ai.rag_engine.reranker import get_reranker
            self.reranker = get_reranker()
        return self.reranker

    # ---------- 主入口 ----------

    def retrieve(
        self,
        query: str,
        knowledge_base_ids: Optional[List[Any]] = None,
        top_k: int = 5,
        vector_top_k: Optional[int] = None,
        bm25_top_k: Optional[int] = None,
        rerank_top_n: Optional[int] = None,
    ) -> List[RetrievedChunk]:
        """
        多路混合召回。

        Args:
            query: 用户查询
            knowledge_base_ids: 知识库 ID 列表（可为 None，此时需外部指定集合名，暂不支持跨库全量）
            top_k: 最终返回条数
            vector_top_k: 向量召回候选数（默认取 config.vector_top_k）
            bm25_top_k: BM25 召回候选数（默认取 config.bm25_top_k）
            rerank_top_n: 重排候选数（默认取 config.reranker_top_n）

        Returns:
            RetrievedChunk 列表，按相关性降序
        """
        vector_top_k = vector_top_k or settings.vector_top_k
        bm25_top_k = bm25_top_k or settings.bm25_top_k
        rerank_top_n = rerank_top_n or settings.reranker_top_n

        collection_names = self._resolve_collections(knowledge_base_ids)
        if not collection_names:
            logger.warning("无可用知识库集合，返回空结果")
            return []

        # 一路：向量召回
        vector_hits: Dict[str, RetrievedChunk] = {}
        query_vec = None
        try:
            query_vec = self._get_embedding().embed_query(query)
        except Exception as e:
            logger.warning(f"查询向量生成失败，仅使用 BM25 召回: {e}")

        store = self._get_vector_store()
        if query_vec is not None:
            for col in collection_names:
                for res in store.search(col, query_vec, top_k=vector_top_k):
                    chunk = self._from_vector_result(res, col)
                    vector_hits[chunk.chunk_id] = chunk

        # 二路：BM25 召回
        bm25_hits: Dict[str, RetrievedChunk] = {}
        bm25 = self._get_bm25()
        for col in collection_names:
            for hit in bm25.search(col, query, top_k=bm25_top_k):
                chunk = self._from_bm25_hit(hit, col)
                bm25_hits[chunk.chunk_id] = chunk

        # 融合 + 去重
        fused = self._fuse(vector_hits, bm25_hits)

        if not fused:
            return []

        # 精排
        fused.sort(key=lambda c: c.score, reverse=True)
        rerank_candidates = fused[:rerank_top_n]
        try:
            reranker = self._get_reranker()
            contents = [c.content for c in rerank_candidates]
            ranked = reranker.rerank(query, contents, top_n=top_k)
            result = [rerank_candidates[i] for i, _ in ranked]
            # 补充重排分数
            for c, (_, score) in zip(result, ranked):
                c.score = score
        except Exception as e:
            logger.warning(f"重排失败，使用融合分数排序: {e}")
            result = fused[:top_k]

        logger.info(
            f"混合召回完成: query={query[:30]}, collections={collection_names}, "
            f"vector={len(vector_hits)}, bm25={len(bm25_hits)}, final={len(result)}"
        )
        return result

    # ---------- 融合算法 ----------

    def _fuse(
        self,
        vector_hits: Dict[str, RetrievedChunk],
        bm25_hits: Dict[str, RetrievedChunk],
    ) -> List[RetrievedChunk]:
        """
        加权融合 + 去重。
        分数归一化到 [0,1] 后按权重加权；同一块两路命中时取加权和。
        """
        if not vector_hits and not bm25_hits:
            return []

        # 归一化
        norm_vector = self._normalize_scores([c.score for c in vector_hits.values()])
        norm_bm25 = self._normalize_scores([c.score for c in bm25_hits.values()])

        all_ids = set(vector_hits) | set(bm25_hits)
        merged: Dict[str, RetrievedChunk] = {}

        for chunk_id in all_ids:
            v = vector_hits.get(chunk_id)
            b = bm25_hits.get(chunk_id)

            if v and b:
                score = self.vector_weight * norm_vector[v.score] + self.bm25_weight * norm_bm25[b.score]
                chunk = v  # 保留向量结果（元数据更全）
                chunk.score = score
            elif v:
                chunk = v
                chunk.score = self.vector_weight * norm_vector[v.score]
            else:
                chunk = b
                chunk.score = self.bm25_weight * norm_bm25[b.score]
            merged[chunk_id] = chunk

        return list(merged.values())

    @staticmethod
    def _normalize_scores(scores: List[float]) -> Dict[float, float]:
        """min-max 归一化到 [0,1]"""
        if not scores:
            return {}
        mx = max(scores)
        mn = min(scores)
        if mx == mn:
            return {s: 1.0 for s in scores}
        return {s: (s - mn) / (mx - mn) for s in scores}

    # ---------- 结果转换 ----------

    @staticmethod
    def _from_vector_result(res, collection_name: str) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=res.chunk_id,
            document_id=res.document_id,
            knowledge_base_id=res.knowledge_base_id or collection_name,
            content=res.content,
            score=res.score,
            page_number=res.page_number,
            chunk_index=res.metadata.get("chunk_index", 0),
            metadata=res.metadata,
        )

    @staticmethod
    def _from_bm25_hit(hit, collection_name: str) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            knowledge_base_id=collection_name,
            content=hit.content,
            score=hit.score,
            page_number=hit.page_number,
            chunk_index=hit.chunk_index,
            metadata=hit.metadata,
        )

    @staticmethod
    def _resolve_collections(knowledge_base_ids: Optional[List[Any]]) -> List[str]:
        """把知识库 ID 列表转换为向量集合名（kb_{id}）"""
        if not knowledge_base_ids:
            return []
        return [f"kb_{kb_id}" for kb_id in knowledge_base_ids if kb_id is not None]
