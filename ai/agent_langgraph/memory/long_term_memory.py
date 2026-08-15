"""
长期用户记忆模块

保存用户业务偏好，跨会话复用。
- 按用户隔离存储偏好条目
- 检索时基于嵌入相似度（缺失则降级为关键词匹配）返回最相关偏好
- 每个用户保留条数受上限约束，超出裁剪最旧条目，防止上下文溢出
- JSON 文件持久化到独立目录（不写入 PostgreSQL，遵守三者分离原则）

参数从 config（agent_long_term_memory_enabled / agent_long_term_memory_window /
AGENT_LONG_TERM_MAX_ITEMS / AGENT_LONG_TERM_DIR）读取。
"""
from __future__ import annotations

import json
import os
import time
from typing import List, Dict, Optional, Any

from ai.agent_langgraph.agent_config import get_agent_config
from utils.text_utils import cosine_similarity, jieba_segment
from utils.logger import get_logger

logger = get_logger(__name__)


class LongTermMemory:
    """长期用户记忆（偏好存储 + 相似度检索 + 裁剪 + 持久化）"""

    def __init__(
        self,
        embedding_client=None,
        max_items: Optional[int] = None,
        storage_dir: Optional[str] = None,
        enabled: Optional[bool] = None,
    ):
        cfg = get_agent_config()
        self.enabled = enabled if enabled is not None else cfg.long_term_enabled
        self.max_items = max_items if max_items is not None else cfg.long_term_max_items
        self.storage_dir = storage_dir or cfg.long_term_dir
        self._embedding_client = embedding_client
        # user_id(str) -> List[{"content": str, "created_at": float}]
        self._store: Dict[str, List[Dict[str, Any]]] = {}
        self._load_from_disk()

    # ---------- 嵌入懒加载 ----------

    def _get_embedding(self):
        if self._embedding_client is None:
            try:
                from utils.embedding_client import get_embedding_client
                self._embedding_client = get_embedding_client()
            except Exception:
                self._embedding_client = None
        return self._embedding_client

    # ---------- 写入 ----------

    def save_preference(self, user_id: Any, content: str) -> None:
        """保存一条用户业务偏好"""
        if not self.enabled or not content or not content.strip():
            return
        uid = str(user_id)
        items = self._store.setdefault(uid, [])
        items.append({"content": content.strip(), "created_at": time.time()})
        # 裁剪：超出上限删除最旧
        if len(items) > self.max_items:
            overflow = len(items) - self.max_items
            del items[:overflow]
            logger.debug(f"长期记忆裁剪: user={uid}, 删除 {overflow} 条旧偏好")
        self._persist()

    # ---------- 检索 ----------

    def retrieve(self, user_id: Any, query: str = "", top_k: Optional[int] = None) -> List[str]:
        """
        检索用户最相关的长期偏好。

        Args:
            user_id: 用户 ID
            query: 当前任务指令（用于相关性排序，空则返回最近条目）
            top_k: 返回条数（默认取 config.long_term_top_k）

        Returns:
            偏好文本列表
        """
        if not self.enabled:
            return []
        cfg = get_agent_config()
        top_k = top_k if top_k is not None else cfg.long_term_top_k
        uid = str(user_id)
        items = self._store.get(uid, [])
        if not items:
            return []

        if not query:
            # 无查询：返回最近保存的条目
            return [it["content"] for it in items[-top_k:][::-1]]

        ranked = self._rank(items, query)
        return [it["content"] for it, _ in ranked[:top_k]]

    def get_all(self, user_id: Any) -> List[str]:
        """获取用户全部偏好（按时间正序）"""
        uid = str(user_id)
        return [it["content"] for it in self._store.get(uid, [])]

    def clear(self, user_id: Optional[Any] = None) -> None:
        """清空记忆（user_id 为空则清空全部）"""
        if user_id is None:
            self._store.clear()
        else:
            self._store.pop(str(user_id), None)
        self._persist()

    # ---------- 内部工具 ----------

    def _rank(self, items: List[Dict[str, Any]], query: str) -> List[tuple]:
        """按与 query 的相关性对偏好条目排序"""
        client = self._get_embedding()
        if client is not None and hasattr(client, "embed_query"):
            try:
                q_vec = client.embed_query(query)
                scored = []
                for it in items:
                    v = client.embed([it["content"]])[0]
                    scored.append((it, cosine_similarity(q_vec, v)))
                scored.sort(key=lambda x: x[1], reverse=True)
                return scored
            except Exception as e:
                logger.warning(f"长期记忆向量检索失败，降级为关键词匹配: {e}")

        # 降级：关键词匹配
        try:
            q_tokens = set(jieba_segment(query, use_stopwords=True))
        except Exception:
            q_tokens = set(query.lower().split())

        scored = []
        for it in items:
            try:
                c_tokens = set(jieba_segment(it["content"], use_stopwords=True))
            except Exception:
                c_tokens = set(it["content"].lower().split())
            overlap = len(q_tokens & c_tokens) if q_tokens else 0
            scored.append((it, float(overlap)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # ---------- 持久化 ----------

    def _file_path(self) -> str:
        os.makedirs(self.storage_dir, exist_ok=True)
        return os.path.join(self.storage_dir, "long_term_memory.json")

    def _persist(self) -> None:
        try:
            with open(self._file_path(), "w", encoding="utf-8") as f:
                json.dump(self._store, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"长期记忆持久化失败: {e}")

    def _load_from_disk(self) -> None:
        try:
            path = self._file_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    self._store = json.load(f)
                logger.debug(f"长期记忆已加载: {len(self._store)} 个用户")
        except Exception as e:
            logger.warning(f"长期记忆加载失败，使用空记忆: {e}")
            self._store = {}
