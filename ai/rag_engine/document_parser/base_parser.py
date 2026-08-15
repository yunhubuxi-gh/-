"""
文档解析器抽象基类与统一数据结构
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class PageText:
    """单页文本"""
    page_number: int
    text: str


@dataclass
class ExtractedImage:
    """
    从文档中提取出的内嵌图片（内存态，尚未落盘）。

    Attributes:
        page_number: 图片所在页码
        image_bytes: 图片二进制内容
        ext: 图片扩展名（png/jpeg，不含点）
        index: 该页内的图片序号（从 0 开始）
    """
    page_number: int
    image_bytes: bytes
    ext: str = "png"
    index: int = 0


@dataclass
class ParsedDocument:
    """
    解析后的文档统一结构

    Attributes:
        title: 文档标题（默认取文件名）
        pages: 按页组织的文本（单页文档也封装为 1 页）
        images: 从文档中提取的内嵌图片（PDF 内嵌图，供多模态向量化）
        metadata: 附加元信息（页数、字符数等）
    """
    title: str
    pages: List[PageText]
    images: List[ExtractedImage] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        """拼接全文（按页换行）"""
        return "\n".join(p.text for p in self.pages if p.text.strip())

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def char_count(self) -> int:
        return len(self.full_text)


class BaseDocumentParser(ABC):
    """文档解析器抽象基类"""

    #: 支持的扩展名列表（小写，含点）
    supported_extensions: List[str] = []

    @abstractmethod
    def parse(self, file_path: str) -> ParsedDocument:
        """
        解析文档，返回统一结构。

        Args:
            file_path: 磁盘上的文档路径（绝对路径）

        Returns:
            ParsedDocument

        Raises:
            FileOperationException: 文件不存在 / 无法解析
        """
        ...
