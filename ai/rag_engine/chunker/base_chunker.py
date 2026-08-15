"""
分块器抽象基类与统一数据结构
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any

from ai.rag_engine.document_parser.base_parser import ParsedDocument


@dataclass
class Chunk:
    """
    文档分块结果

    Attributes:
        chunk_id: 全局唯一块 ID（格式 doc_{document_id}:{chunk_index}）
        document_id: 所属文档 ID（str）
        text: 块文本内容
        page_number: 块起始位置所在页码（用于引用溯源）
        chunk_index: 块在文档内的序号（从 0 开始）
        start_char: 块在全文中的起始字符偏移
        end_char: 块在全文中的结束字符偏移
    """
    chunk_id: str
    document_id: str
    text: str
    page_number: int
    chunk_index: int
    start_char: int = 0
    end_char: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_vector_metadata(self, knowledge_base_id: str, document_name: str = "") -> Dict[str, Any]:
        """
        生成写入向量库的元数据（不含正文，正文由向量库单独存 document 字段）。

        Args:
            knowledge_base_id: 知识库 ID
            document_name: 文档名（用于引用展示）
        """
        meta = {
            "document_id": self.document_id,
            "knowledge_base_id": str(knowledge_base_id),
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "document_name": document_name or self.metadata.get("document_name", ""),
        }
        meta.update({k: v for k, v in self.metadata.items() if k not in meta})
        return meta


class BaseChunker(ABC):
    """分块器抽象基类"""

    @abstractmethod
    def split(self, parsed: ParsedDocument, document_id: str) -> List[Chunk]:
        """
        将解析后的文档切分为多个块。

        Args:
            parsed: 解析后的文档
            document_id: 文档 ID（str）

        Returns:
            Chunk 列表
        """
        ...
