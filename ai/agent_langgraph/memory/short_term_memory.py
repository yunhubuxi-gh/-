"""
短期会话记忆模块

维护当前对话上下文，采用「滑动窗口」裁剪策略：
只保留最近 window 条消息，超出则丢弃最旧消息，防止上下文溢出。

窗口大小从 config（agent_short_term_memory_window）读取。
"""
from __future__ import annotations

from typing import List, Dict, Optional

from ai.agent_langgraph.agent_config import get_agent_config
from utils.logger import get_logger

logger = get_logger(__name__)


class ShortTermMemory:
    """短期会话记忆（滑动窗口）"""

    def __init__(self, window: Optional[int] = None):
        self.window = window if window is not None else get_agent_config().short_term_window
        self._messages: List[Dict[str, str]] = []

    def add(self, role: str, content: str) -> None:
        """追加一条消息"""
        if not content or not content.strip():
            return
        self._messages.append({"role": role, "content": content})
        self._truncate()

    def add_user(self, content: str) -> None:
        self.add("user", content)

    def add_assistant(self, content: str) -> None:
        self.add("assistant", content)

    def add_tool(self, content: str) -> None:
        self.add("tool", content)

    def get_context(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """返回当前对话上下文（最近 limit 条，默认全部窗口内消息）"""
        if limit is None:
            return list(self._messages)
        return self._messages[-limit:] if limit > 0 else []

    def to_messages(self) -> List[Dict[str, str]]:
        """返回可直接传给 LLM 的消息列表"""
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def _truncate(self) -> None:
        """滑动窗口裁剪，超出 window 条则丢弃最旧消息"""
        if len(self._messages) > self.window:
            overflow = len(self._messages) - self.window
            self._messages = self._messages[overflow:]
            logger.debug(f"短期记忆裁剪: 丢弃 {overflow} 条旧消息")

    def __len__(self) -> int:
        return len(self._messages)
