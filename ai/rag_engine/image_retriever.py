"""
图片多模态向量化与检索模块

职责（与文本混合检索完全独立，加法式扩展）：
- 图片入库：调用多模态嵌入客户端生成图片向量，写入独立集合 kb_{id}_img
- 图片检索：把用户 query 送入同一多模态模型得到查询向量，检索图片向量库

存储边界：
- 图片原始文件 -> 文件系统（上传目录），路径写入向量元数据 image_path
- 图片向量 -> 向量库集合 kb_{id}_img（与文本向量 kb_{id} 分离，不同向量空间）
- 元数据标记：chunk_type=image / document_id / page_number / document_name / image_path

关闭开关（ENABLE_IMAGE_EMBED=false）或模型不可用时，本模块所有方法返回空，完全退回原行为。
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional

from config.settings import settings
from ai.rag_engine.hybrid_retriever import RetrievedChunk
from utils.logger import get_logger

logger = get_logger(__name__)

# 图片向量独立集合后缀
_IMG_COLLECTION_SUFFIX = "_img"


def _img_collection(kb_id: Any) -> str:
    return f"kb_{kb_id}{_IMG_COLLECTION_SUFFIX}"


class ImageRetriever:
    """图片多模态检索器（独立于文本 HybridRetriever）"""

    def __init__(self, vector_store=None, multimodal_client=None):
        self.vector_store = vector_store
        self.multimodal_client = multimodal_client

    # ---------- 懒加载 ----------

    def _get_vector_store(self):
        if self.vector_store is None:
            from ai.rag_engine.vector_store import get_vector_store
            self.vector_store = get_vector_store()
        return self.vector_store

    def _get_client(self):
        if self.multimodal_client is None:
            from utils.multimodal_embedding_client import get_multimodal_client
            self.multimodal_client = get_multimodal_client()
        return self.multimodal_client

    # ---------- 图片入库 ----------

    def index_images(
        self,
        knowledge_base_id: Any,
        document_id: Any,
        document_name: str,
        images: List[Dict[str, Any]],
    ) -> int:
        """
        将图片向量写入独立集合。

        Args:
            knowledge_base_id: 知识库 ID
            document_id: 文档 ID
            document_name: 文档名（用于引用展示）
            images: [{image_path, page_number, index}]，index 为该页内图片序号

        Returns:
            写入的图片数量（关闭/失败返回 0）
        """
        if not images:
            return 0
        client = self._get_client()
        if client is None:
            logger.debug("多模态客户端不可用，跳过图片向量化")
            return 0

        paths = [img["image_path"] for img in images]
        try:
            vectors = client.embed_images(paths)
        except Exception as e:
            logger.warning(f"图片向量化失败，跳过: {e}")
            return 0

        store = self._get_vector_store()
        collection = _img_collection(knowledge_base_id)
        ids: List[str] = []
        metas: List[Dict] = []
        docs: List[str] = []
        for img, vec in zip(images, vectors):
            chunk_id = f"img_{document_id}:{img.get('page_number', 1)}:{img.get('index', 0)}"
            placeholder = f"[图片] {document_name} 第{img.get('page_number', 1)}页"
            ids.append(chunk_id)
            docs.append(placeholder)
            metas.append({
                "document_id": str(document_id),
                "knowledge_base_id": str(knowledge_base_id),
                "page_number": img.get("page_number", 1),
                "chunk_index": img.get("index", 0),
                "document_name": document_name,
                "chunk_type": "image",
                "image_path": img["image_path"],
                "format": img.get("ext", ""),
            })

        try:
            store.upsert(collection, ids, vectors, docs, metas)
        except Exception as e:
            logger.warning(f"图片向量写入失败: {e}")
            return 0

        logger.info(f"图片向量化完成: kb={knowledge_base_id}, doc={document_id}, images={len(ids)}")
        return len(ids)

    def clear_document_images(self, knowledge_base_id: Any, document_id: Any) -> None:
        """删除某文档的全部图片向量（文档删除 / 重建时调用，避免孤儿向量）"""
        try:
            self._get_vector_store().delete_by_document_id(
                _img_collection(knowledge_base_id), str(document_id),
            )
        except Exception as e:
            logger.warning(
                f"清除文档图片向量失败: kb={knowledge_base_id}, doc={document_id}, err={e}"
            )

    # ---------- 图片检索 ----------

    def retrieve_images(
        self,
        query: str,
        knowledge_base_ids: Optional[List[Any]] = None,
        top_k: Optional[int] = None,
    ) -> List[RetrievedChunk]:
        """用文字 query 检索图片（跨模态召回），返回图片类型 RetrievedChunk"""
        client = self._get_client()
        if client is None:
            return []
        if not knowledge_base_ids:
            return []

        try:
            query_vec = client.embed_query(query)
        except Exception as e:
            logger.warning(f"查询多模态向量生成失败，跳过图片检索: {e}")
            return []

        top_k = top_k or settings.image_vector_top_k
        store = self._get_vector_store()

        results: List[RetrievedChunk] = []
        for kb_id in knowledge_base_ids:
            for res in store.search(_img_collection(kb_id), query_vec, top_k=top_k):
                results.append(RetrievedChunk(
                    chunk_id=res.chunk_id,
                    document_id=res.document_id,
                    knowledge_base_id=str(kb_id),
                    content=res.content,
                    score=res.score,
                    page_number=res.page_number,
                    chunk_index=res.metadata.get("chunk_index", 0),
                    metadata=res.metadata,
                ))

        results.sort(key=lambda c: c.score, reverse=True)
        results = results[:top_k]
        logger.info(f"图片检索完成: query={query[:30]}, hits={len(results)}")
        return results


# 单例
_image_retriever: Optional[ImageRetriever] = None


def get_image_retriever() -> ImageRetriever:
    global _image_retriever
    if _image_retriever is None:
        _image_retriever = ImageRetriever()
    return _image_retriever


def reset_image_retriever() -> None:
    global _image_retriever
    _image_retriever = None
