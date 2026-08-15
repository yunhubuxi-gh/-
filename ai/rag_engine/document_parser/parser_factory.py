"""
文档解析器工厂

根据文件扩展名选择对应解析器，上层业务只需调用 parse_document()。
"""
from __future__ import annotations

import os
from typing import Dict, Optional

from ai.rag_engine.document_parser.base_parser import (
    BaseDocumentParser,
    ParsedDocument,
)
from ai.rag_engine.document_parser.pdf_parser import PDFParser
from ai.rag_engine.document_parser.docx_parser import DocxParser
from ai.rag_engine.document_parser.md_parser import MarkdownParser
from ai.rag_engine.document_parser.image_parser import ImageParser
from utils.exceptions import ValidationException
from utils.error_codes import DOC_UNSUPPORTED_TYPE
from utils.logger import get_logger

logger = get_logger(__name__)

# 扩展名 -> 解析器实例（懒初始化）
_parser_registry: Dict[str, BaseDocumentParser] = {}


def _build_registry() -> Dict[str, BaseDocumentParser]:
    """构建解析器注册表"""
    registry: Dict[str, BaseDocumentParser] = {}
    for parser_cls in (PDFParser, DocxParser, MarkdownParser, ImageParser):
        parser = parser_cls()
        for ext in parser.supported_extensions:
            registry[ext] = parser
    return registry


def get_parser(file_path: str) -> BaseDocumentParser:
    """
    根据文件扩展名获取解析器。

    Raises:
        ValidationException: 不支持的文件类型
    """
    ext = os.path.splitext(file_path)[1].lower()
    if not _parser_registry:
        _parser_registry.update(_build_registry())

    parser = _parser_registry.get(ext)
    if parser is None:
        raise ValidationException(
            DOC_UNSUPPORTED_TYPE, f"不支持的文档类型: {ext or '(无扩展名)'}"
        )
    return parser


def parse_document(file_path: str) -> ParsedDocument:
    """
    解析文档统一入口。

    Args:
        file_path: 磁盘文档路径（绝对路径）

    Returns:
        ParsedDocument 统一结构
    """
    parser = get_parser(file_path)
    logger.info(f"开始解析文档: {file_path}")
    parsed = parser.parse(file_path)
    logger.info(
        f"解析完成: title={parsed.title}, pages={parsed.page_count}, "
        f"chars={parsed.char_count}"
    )
    return parsed
