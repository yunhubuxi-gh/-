"""
图片多模态向量化与检索模块

职责（与文本混合检索完全独立，加法式扩展）：
- 图片入库：逐张调用多模态嵌入客户端生成图片向量，写入独立集合 kb_{id}_img
- 图片检索：把用户 query 送入同一多模态模型得到查询向量，检索图片向量库

存储边界：
- 图片原始文件 -> 文件系统（上传目录），路径写入向量元数据 image_path
- 图片向量 -> 向量库集合 kb_{id}_img（与文本向量 kb_{id} 分离，不同向量空间）
- 元数据标记：content_type="image" / chunk_type="image" / source_file / page_num / image_path
- 禁止把图片二进制存入向量库（只存路径与元数据）

容错降级【最重要】：
- 逐张图片 try-except，单张图片向量化失败只跳过该图，不影响其他图片、不影响文档整体导入。
- 关闭开关（ENABLE_IMAGE_EMBED=false）或模型不可用时，本模块所有方法返回空，完全退回原行为。
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple

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
    ) -> Tuple[int, List[str]]:
        """
        将图片向量逐张写入独立集合。

        Args:
            knowledge_base_id: 知识库 ID
            document_id: 文档 ID
            document_name: 文档名（用于引用展示）
            images: [{image_path, page_number, index, ext}]，image_path 为「预处理后副本」路径

        Returns:
            (成功写入数, 警告列表)。单张失败只记录警告并跳过，不抛异常。
        """
        warnings: List[str] = []
        if not images:
            return 0, warnings

        client = self._get_client()
        if client is None:
            warnings.append("多模态客户端不可用，已跳过全部图片向量化（文本入库不受影响）")
            return 0, warnings

        store = self._get_vector_store()
        collection = _img_collection(knowledge_base_id)

        ids: List[str] = []
        metas: List[Dict] = []
        docs: List[str] = []
        vecs: List[List[float]] = []

        # 逐张处理：每张图片独立 try-except，单张失败绝不拖垮整体
        for img in images:
            page = img.get("page_number", 1)
            idx = img.get("index", 0)
            path = img.get("image_path", "")
            label = f"doc_{document_id}_p{page}_{idx}"
            try:
                vec = client.embed_image(path)
                if not vec:
                    raise ValueError("图片向量为空")
                chunk_id = f"img_{document_id}:{page}:{idx}"
                ids.append(chunk_id)
                vecs.append(vec)
                docs.append(f"[图片] {document_name} 第{page}页")
                metas.append({
                    "document_id": str(document_id),
                    "knowledge_base_id": str(knowledge_base_id),
                    "page_number": page,
                    "chunk_index": idx,
                    "document_name": document_name,
                    "chunk_type": "image",
                    "content_type": "image",
                    "source_file": document_name,
                    "page_num": page,
                    "image_path": path,
                    "format": img.get("ext", ""),
                })
            except Exception as e:
                logger.warning(f"图片向量化失败，跳过该图（不影响文档整体导入）: {label}, err={e}")
                warnings.append(f"图片第{page}页第{idx}张向量化失败：{e}")

        if not ids:
            return 0, warnings

        try:
            store.upsert(collection, ids, vecs, docs, metas)
        except Exception as e:
            logger.warning(f"图片向量写入向量库失败: {e}")
            warnings.append(f"图片向量写入向量库失败：{e}")
            return 0, warnings

        logger.info(
            f"图片向量化完成: kb={knowledge_base_id}, doc={document_id}, "
            f"成功={len(ids)}, 失败={len(warnings)}"
        )
        return len(ids), warnings

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
            try:
                hits = store.search(_img_collection(kb_id), query_vec, top_k=top_k)
            except Exception as e:
                logger.warning(f"图片向量检索失败: kb={kb_id}, err={e}")
                continue
            for res in hits:
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
