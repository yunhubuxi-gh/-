"""
文档版本管理模块

文档更新时，需要先清理旧版本的向量与 BM25 索引，再写入新版本，
保证检索结果始终对应最新版本，同时支持版本回滚（回滚 = 重新索引旧版本文件）。

本模块只提供「索引编排原语」，由业务服务层（步骤5）依据 DB 中的
DocumentVersion.file_path 驱动，完成版本重建与回滚。
"""
from __future__ import annotations

from typing import List

from ai.rag_engine.chunker.base_chunker import Chunk
from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class DocVersionManager:
    """文档版本索引编排器"""

    def __init__(self, vector_store=None, bm25_engine=None, embedding_client=None):
        self.vector_store = vector_store
        self.bm25_engine = bm25_engine
        self.embedding_client = embedding_client

    # ---------- 懒加载 ----------

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

    # ---------- 索引编排 ----------

    def index_chunks(
        self,
        collection_name: str,
        chunks: List[Chunk],
        knowledge_base_id: str,
    ) -> int:
        """
        将分块写入向量库 + BM25 索引。

        Returns:
            写入的块数量
        """
        if not chunks:
            return 0

        store = self._get_vector_store()
        bm25 = self._get_bm25()
        embedding_client = self._get_embedding()

        texts = [c.text for c in chunks]
        # embedding 按批调用（避免一次性把全文塞进单个请求/单次前向，控制内存与请求大小）
        embeddings = self._embed_batched(embedding_client, texts)

        # 向量库单批写入（一批完成再落盘；Chroma/Milvus 内部按单次 upsert 持久化）
        store.upsert(
            collection_name=collection_name,
            ids=[c.chunk_id for c in chunks],
            vectors=embeddings,
            documents=texts,
            metadatas=[c.to_vector_metadata(knowledge_base_id) for c in chunks],
        )
        bm25.add_documents(collection_name, chunks)
        # 持久化 BM25 索引到磁盘，重启后端后可恢复，避免 BM25 召回失效
        try:
            bm25.save(collection_name)
        except Exception as e:
            logger.warning(f"BM25 索引持久化失败（不影响本次入库）: {e}")
        logger.info(f"写入索引: collection={collection_name}, chunks={len(chunks)}")
        return len(chunks)

    @staticmethod
    def _embed_batched(embedding_client, texts: List[str]) -> List[List[float]]:
        """按 settings.embedding_batch_size 分批生成嵌入，再拼接（顺序与输入一致）"""
        batch_size = max(1, int(settings.embedding_batch_size))
        vectors: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            vectors.extend(embedding_client.embed(batch))
        return vectors

    def clear_document_chunks(
        self,
        collection_name: str,
        document_id: str,
    ) -> None:
        """删除某文档在向量库与 BM25 中的全部索引"""
        store = self._get_vector_store()
        bm25 = self._get_bm25()
        store.delete_by_document_id(collection_name, document_id)
        bm25.remove_documents(collection_name, [document_id])
        logger.info(f"清除文档索引: collection={collection_name}, doc={document_id}")

    def reindex_document(
        self,
        collection_name: str,
        document_id: str,
        knowledge_base_id: str,
        chunks: List[Chunk],
    ) -> int:
        """
        重建某文档索引（先清旧、再写新），用于版本更新与回滚。

        Returns:
            新写入的块数量
        """
        self.clear_document_chunks(collection_name, document_id)
        return self.index_chunks(collection_name, chunks, knowledge_base_id)
