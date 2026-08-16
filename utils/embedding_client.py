"""
嵌入模型客户端封装
统一封装嵌入向量生成接口，支持：
- BGE 系列（本地 HuggingFace，推荐中文场景）
- OpenAI 兼容接口（text-embedding-ada-002 等）

上层模块（RAG / 长期记忆 / 语义分块）统一通过此客户端生成嵌入。
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import List, Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def _apply_hf_offline() -> None:
    """按配置设置 HuggingFace 离线模式，避免加载本地模型时联网校验失败"""
    if settings.hf_hub_offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"


class BaseEmbeddingClient(ABC):
    """嵌入模型客户端抽象基类"""

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        生成文本嵌入向量

        Args:
            texts: 文本列表

        Returns:
            嵌入向量列表，顺序与输入一致
        """
        ...

    @abstractmethod
    def embed_query(self, query: str) -> List[float]:
        """
        生成查询文本的嵌入（部分模型对 query 和 doc 使用不同前缀）

        Args:
            query: 查询文本

        Returns:
            嵌入向量
        """
        ...


class OpenAIEmbeddingClient(BaseEmbeddingClient):
    """OpenAI 兼容接口的嵌入客户端"""

    def __init__(self):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError("openai 未安装，请执行 pip install openai") from e

        self.model = settings.embedding_model
        base_url = settings.embedding_base_url or settings.llm_base_url
        api_key = settings.embedding_api_key or settings.llm_api_key

        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=settings.llm_timeout)
        self.dimension = settings.embedding_dimension
        logger.info(f"OpenAI 嵌入客户端初始化完成: model={self.model}")

    def embed(self, texts: List[str]) -> List[List[float]]:
        # 过滤空字符串，避免 API 报错
        non_empty = [(i, t) for i, t in enumerate(texts) if t.strip()]
        if not non_empty:
            return [[0.0] * self.dimension for _ in texts]

        indices, batch_texts = zip(*non_empty)
        resp = self._client.embeddings.create(
            model=self.model,
            input=list(batch_texts),
        )
        # 按原位置填充
        result = [[0.0] * self.dimension for _ in texts]
        for idx, emb_data in zip(indices, resp.data):
            result[idx] = emb_data.embedding
        return result

    def embed_query(self, query: str) -> List[float]:
        return self.embed([query])[0]


class BgeEmbeddingClient(BaseEmbeddingClient):
    """
    BGE 中文嵌入模型客户端（本地运行 HuggingFace 模型）
    推荐使用 BAAI/bge-small-zh-v1.5 / bge-large-zh-v1.5
    """

    # BGE 模型对文档和查询使用不同前缀
    QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
    DOC_PREFIX = ""  # 文档不需要前缀

    def __init__(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "sentence-transformers 未安装，请执行 pip install sentence-transformers"
            ) from e

        _apply_hf_offline()
        model_name = settings.embedding_model
        device = getattr(settings, "embedding_device", "cpu")
        self._model = SentenceTransformer(model_name, device=device)
        self.dimension = self._model.get_sentence_embedding_dimension()
        self.batch_size = settings.embedding_batch_size
        logger.info(f"BGE 嵌入客户端初始化完成: model={model_name}, dim={self.dimension}")

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        # 文档嵌入不加前缀
        embeddings = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def embed_query(self, query: str) -> List[float]:
        # 查询加上 BGE 专用前缀
        prefixed = self.QUERY_PREFIX + query
        emb = self._model.encode(
            [prefixed],
            batch_size=1,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return emb[0].tolist()


# ==================== 工厂函数 ====================
_instance: Optional[BaseEmbeddingClient] = None


def get_embedding_client() -> BaseEmbeddingClient:
    """获取嵌入客户端单例，根据配置自动选择实现"""
    global _instance
    if _instance is not None:
        return _instance

    provider = settings.embedding_provider.lower()
    if provider in ("openai", "deepseek", "qwen"):
        _instance = OpenAIEmbeddingClient()
    elif provider in ("bge", "huggingface", "sentence_transformers"):
        _instance = BgeEmbeddingClient()
    else:
        raise ValueError(f"不支持的嵌入模型提供商: {provider}")

    return _instance


def reset_embedding_client() -> None:
    """重置嵌入客户端（测试用）"""
    global _instance
    _instance = None
