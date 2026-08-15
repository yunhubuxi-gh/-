"""
双 Agent 工作流 RAG 检索辅助

命题 Agent 与校验评审 Agent 都必须调用 RAG 检索课程库课件原文，
本模块统一封装「多查询检索 → 去重 → 拼接上下文」，并返回检索日志供轨迹展示。
"""
from __future__ import annotations

from typing import Any, List, Tuple


def retrieve_material(
    rag_pipeline,
    knowledge_base_id: int,
    queries: List[str],
    top_k: int,
) -> Tuple[str, List[dict]]:
    """
    对多个 query 依次检索课程库，去重后拼接课件原文。

    Returns:
        (格式化后的课件原文上下文, 检索日志 [{query, count}])
    """
    context_parts: List[str] = []
    log: List[dict] = []
    seen = set()

    for q in queries:
        try:
            chunks = rag_pipeline.retrieve(q, [knowledge_base_id], top_k=top_k)
        except Exception as e:
            log.append({"query": q, "count": 0, "error": str(e)})
            continue
        log.append({"query": q, "count": len(chunks)})
        for c in chunks:
            if c.chunk_id in seen:
                continue
            seen.add(c.chunk_id)
            doc = c.document_name or f"文档{c.document_id}"
            page = f"第{c.page_number}页" if c.page_number else ""
            context_parts.append(f"【{doc}{page}】\n{c.content}")

    return "\n\n".join(context_parts), log
