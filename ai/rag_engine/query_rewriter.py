"""
查询改写（Query Rewriting）模块

作用：对用户原始提问生成 1~2 个衍生检索查询，用多查询召回提升命中率，
解决「知识库明明有内容却检索不到」的问题。

设计要点：
- 调用 LLM（复用 utils.llm_client 单例）生成改写，结果与原问题一起去重后参与检索
- 失败 / 超时 / 解析不出结果时优雅降级，仅返回原问题，不中断 RAG 主链路
- 开关 settings.query_rewrite_enabled；衍生个数 settings.query_rewrite_count（1~2）
- 不修改 LLM 客户端，仅通过 .chat(..., timeout=...) 传入本次超时

边界：
- 只做「检索查询改写」，不改变用户原始问题，不影响回答生成
- LLM 生成不稳定，解析逻辑做多格式兜底（JSON 数组 / 逐行 / 带序号）
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "你是检索查询改写助手。请把用户的原始问题改写成更适合知识库检索的查询，"
    "可以：同义替换、拆分复合问题、补充核心关键词。"
    f"最多输出 {settings.query_rewrite_count} 个改写查询，每个单独一行，不要编号、不要解释。"
)


class QueryRewriter:
    """查询改写器（基于 LLM）"""

    def __init__(self, llm_client=None):
        self._llm_client = llm_client

    def _get_llm(self):
        if self._llm_client is None:
            from utils.llm_client import get_llm_client
            self._llm_client = get_llm_client()
        return self._llm_client

    def rewrite(self, query: str) -> List[str]:
        """
        生成衍生查询，返回 [原问题, 衍生1, 衍生2, ...]。
        任何异常均降级为 [原问题]。
        """
        if not settings.query_rewrite_enabled:
            return [query]

        try:
            llm = self._get_llm()
            if llm is None:
                return [query]

            raw = llm.chat(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f"原始问题：{query}"},
                ],
                temperature=0.0,
                max_tokens=settings.query_rewrite_max_tokens,
                timeout=settings.query_rewrite_timeout,
            )
            derived = self._parse(raw or "")
        except Exception as e:
            logger.warning(f"query 改写失败，退回原问题: {e}")
            return [query]

        max_derived = max(1, min(int(settings.query_rewrite_count), 2))
        result = [query]
        for q in derived:
            if q and q != query and len(result) - 1 < max_derived:
                result.append(q)
        return result

    @staticmethod
    def _parse(raw: str) -> List[str]:
        """从 LLM 输出中解析衍生查询（多格式兜底）"""
        raw = (raw or "").strip()
        if not raw:
            return []

        # 1. JSON 数组
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass

        # 2. 逐行 + 去序号/符号
        result: List[str] = []
        for line in raw.split("\n"):
            line = line.strip()
            line = re.sub(r"^\s*(\d+[.、\)\-]|[-*·])\s*", "", line)
            line = line.strip().strip('"').strip("'")
            if line and line not in result:
                result.append(line)
        return result


# 单例
_rewriter: Optional[QueryRewriter] = None


def get_query_rewriter(llm_client=None) -> QueryRewriter:
    """获取查询改写器单例（可注入 llm_client 供测试）"""
    global _rewriter
    if _rewriter is None or llm_client is not None:
        _rewriter = QueryRewriter(llm_client=llm_client)
    return _rewriter


def reset_query_rewriter() -> None:
    global _rewriter
    _rewriter = None
