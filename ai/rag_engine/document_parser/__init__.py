"""
文档解析器子模块

支持文档类型：PDF / DOCX / Markdown / TXT
- 扫描版 PDF 自动调用 OCR 识别（失败优雅降级）
- 过滤页眉页脚等重复噪声

对外统一入口：parse_document(file_path) -> ParsedDocument
"""
from ai.rag_engine.document_parser.base_parser import (
    ParsedDocument,
    PageText,
    ExtractedImage,
    BaseDocumentParser,
)
from ai.rag_engine.document_parser.pdf_parser import PDFParser
from ai.rag_engine.document_parser.docx_parser import DocxParser
from ai.rag_engine.document_parser.md_parser import MarkdownParser
from ai.rag_engine.document_parser.image_parser import ImageParser
from ai.rag_engine.document_parser.parser_factory import parse_document, get_parser

__all__ = [
    "ParsedDocument",
    "PageText",
    "ExtractedImage",
    "BaseDocumentParser",
    "PDFParser",
    "DocxParser",
    "MarkdownParser",
    "ImageParser",
    "parse_document",
    "get_parser",
]
