"""
引用来源标注模块

为 RAG 回答附带可溯源的引用：文档名 + 页码 + 块编号 + 原文片段。
支持：
- 生成结构化引用列表（用于前端渲染 / 入库 citations JSON）
- 在回答文本中注入行内引用标记 [1][2]，并附文末参考文献列表
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any

from ai.rag_engine.hybrid_retriever import RetrievedChunk


@dataclass
class Citation:
    """单条引用"""
    index: int
    document_id: str
    document_name: str
    page_number: int
    chunk_index: int
    chunk_id: str
    excerpt: str = ""          # 原文片段（截断）
    score: float = 0.0
    chunk_type: str = "text"   # 片段类型：text / image（兼容旧字段）
    content_type: str = "text"  # 结果类型：text / image（新增字段，供前端按类型渲染）
    image_path: str = ""       # 图片片段时携带本地图片路径

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_label(self) -> str:
        """人类可读引用标签：文档名 · 第X页 · 块Y"""
        parts = [self.document_name or f"文档{self.document_id}"]
        if self.page_number:
            parts.append(f"第{self.page_number}页")
        parts.append(f"块{self.chunk_index + 1}")
        return " · ".join(parts)


def build_citations(chunks: List[RetrievedChunk], excerpt_length: int = 80) -> List[Citation]:
    """
    由检索结果生成引用列表（去重 + 稳定编号）。

    Args:
        chunks: 重排后的检索结果
        excerpt_length: 原文片段截断长度
    """
    citations: List[Citation] = []
    seen: set = set()

    for chunk in chunks:
        key = chunk.chunk_id
        if key in seen:
            continue
        seen.add(key)

        excerpt = chunk.content.strip()
        if len(excerpt) > excerpt_length:
            excerpt = excerpt[:excerpt_length] + "…"

        chunk_type = chunk.metadata.get("chunk_type", "text")
        content_type = chunk.metadata.get("content_type", chunk_type)
        citations.append(Citation(
            index=len(citations) + 1,
            document_id=chunk.document_id,
            document_name=chunk.document_name,
            page_number=chunk.page_number or 0,
            chunk_index=chunk.chunk_index,
            chunk_id=chunk.chunk_id,
            excerpt=excerpt,
            score=chunk.score,
            chunk_type=chunk_type,
            content_type=content_type,
            image_path=chunk.metadata.get("image_path", ""),
        ))
    return citations


def format_reference_list(citations: List[Citation]) -> str:
    """生成 Markdown 参考文献列表"""
    if not citations:
        return ""
    lines = ["\n\n**参考来源：**"]
    for c in citations:
        excerpt = f" — {c.excerpt}" if c.excerpt else ""
        lines.append(f"[{c.index}] {c.to_label()}{excerpt}")
    return "\n".join(lines)


def annotate_answer(answer: str, citations: List[Citation]) -> str:
    """
    在回答末尾附加引用列表。

    Args:
        answer: 模型回答文本
        citations: 引用列表
    """
    if not citations:
        return answer
    return answer + format_reference_list(citations)
