"""
BGE-Rerank 重排模块

- BgeReranker 基于 FlagEmbedding 的 FlagReranker（BAAI/bge-reranker-base 等）
- 模型未安装 / 初始化失败时，get_reranker() 降级为 OverlapReranker（词重叠打分）
  保证重排环节始终可用，不因模型缺失中断 RAG 链路

参数读取 config：reranker_model / reranker_top_n / reranker_device
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple, Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class BaseReranker(ABC):
    """重排器抽象基类"""

    @abstractmethod
    def rerank(self, query: str, documents: List[str], top_n: int) -> List[Tuple[int, float]]:
        """
        对候选文档重排序。

        Args:
            query: 查询文本
            documents: 候选文档文本列表
            top_n: 返回前 top_n 条

        Returns:
            [(原始索引, 相关性分数)]，按分数降序
        """
        ...


class BgeReranker(BaseReranker):
    """基于 FlagEmbedding 的 BGE-Rerank 精排器"""

    def __init__(self, model_name: str | None = None, device: str | None = None,
                 use_fp16: bool = True):
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as e:
            raise ImportError(
                "FlagEmbedding 未安装，请执行 pip install FlagEmbedding，"
                "或使用 OverlapReranker 兜底"
            ) from e

        self.model_name = model_name or settings.reranker_model
        self.device = device or settings.reranker_device
        self._model = FlagReranker(self.model_name, device=self.device, use_fp16=use_fp16)
        logger.info(f"BGE-Rerank 模型加载完成: {self.model_name}, device={self.device}")

    def rerank(self, query: str, documents: List[str], top_n: int) -> List[Tuple[int, float]]:
        if not documents:
            return []
        pairs = [[query, doc] for doc in documents]
        scores = self._model.compute_score(pairs, normalize=True)
        if isinstance(scores, (int, float)):
            scores = [scores]
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_n]
        return [(i, float(s)) for i, s in ranked]


class OverlapReranker(BaseReranker):
    """
    词重叠打分兜底重排器（无模型时使用）

    分数 = 查询词与文档词的集合重叠比例（Jaccard 近似），
    用词频加权增强。仅用于模型缺失时的降级，保证链路可用。
    """

    def __init__(self):
        from utils.text_utils import jieba_segment
        self._tokenize = jieba_segment

    def _tokens(self, text: str) -> set:
        try:
            return set(self._tokenize(text, use_stopwords=True))
        except Exception:
            return set(text.lower().split())

    def rerank(self, query: str, documents: List[str], top_n: int) -> List[Tuple[int, float]]:
        q_tokens = self._tokens(query)
        if not q_tokens:
            return []
        scored = []
        for i, doc in enumerate(documents):
            d_tokens = self._tokens(doc)
            if not d_tokens:
                scored.append((i, 0.0))
                continue
            overlap = len(q_tokens & d_tokens)
            union = len(q_tokens | d_tokens)
            score = overlap / union if union else 0.0
            scored.append((i, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]


# 全局单例
_reranker: Optional[BaseReranker] = None
_reranker_initialized = False


def get_reranker() -> BaseReranker:
    """
    获取重排器单例。优先 BGE-Rerank 模型，不可用时降级为词重叠重排。

    Returns:
        BaseReranker 实例（保证非空）
    """
    global _reranker, _reranker_initialized
    if _reranker_initialized:
        return _reranker

    _reranker_initialized = True
    try:
        _reranker = BgeReranker()
    except Exception as e:
        logger.warning(f"BGE-Rerank 模型不可用，降级为词重叠重排: {e}")
        _reranker = OverlapReranker()
    return _reranker


def reset_reranker() -> None:
    """重置重排器（测试用）"""
    global _reranker, _reranker_initialized
    _reranker = None
    _reranker_initialized = False
