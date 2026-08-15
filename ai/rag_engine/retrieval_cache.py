"""
检索结果缓存（内存 TTL 缓存）

作用：重复提问直接命中缓存，跳过 query 改写 / 向量召回 / BM25 / 重排，显著降低问答延迟。

设计要点：
- 键 = (query, 知识库列表, top_k)，值 = 检索结果列表（RetrievedChunk）
- TTL 过期 + 最大条目数上限（超出淘汰最旧条目）
- 线程安全（RAG 检索可能被多个请求并发触发）
- 开关由 settings.rag_cache_enabled 控制，关闭时不启用

边界：
- 只缓存检索结果（文本 + 图片 chunk 的合并结果），不缓存 LLM 生成的回答
- 纯内存实现，进程重启即失效（符合「私有知识库」场景，无跨进程一致性需求）
"""
from __future__ import annotations

import threading
import time
from typing import Any, List, Optional, Tuple

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class RetrievalCache:
    """TTL 内存缓存"""

    def __init__(self, ttl: int | None = None, max_size: int | None = None):
        self.ttl = ttl if ttl is not None else settings.rag_cache_ttl
        self.max_size = max_size if max_size is not None else settings.rag_cache_max_size
        self._data: dict = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Optional[List]:
        """命中返回结果列表（浅拷贝），未命中/过期返回 None"""
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, ts = item
            if time.time() - ts > self.ttl:
                self._data.pop(key, None)
                return None
            return list(value)

    def set(self, key: Any, value: List) -> None:
        """写入缓存（超出上限时淘汰最旧条目）"""
        with self._lock:
            if len(self._data) >= self.max_size and key not in self._data:
                oldest = min(self._data, key=lambda k: self._data[k][1])
                self._data.pop(oldest, None)
            self._data[key] = (list(value), time.time())

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._data)


# 全局单例（跨 RagPipeline 实例共享，命中率更高）
_cache: Optional[RetrievalCache] = None


def get_retrieval_cache() -> Optional[RetrievalCache]:
    """获取检索缓存单例；缓存开关关闭时返回 None（调用方跳过缓存）"""
    global _cache
    if not settings.rag_cache_enabled:
        return None
    if _cache is None:
        _cache = RetrievalCache()
    return _cache


def reset_retrieval_cache() -> None:
    """重置缓存（测试用）"""
    global _cache
    _cache = None
