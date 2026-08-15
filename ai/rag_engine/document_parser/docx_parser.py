"""
DOCX（Word）文档解析器（python-docx）

提取正文段落与表格文本，按「逻辑页」近似分页。
"""
from __future__ import annotations

import os
from typing import List

from ai.rag_engine.document_parser.base_parser import (
    BaseDocumentParser,
    ParsedDocument,
    PageText,
)
from utils.exceptions import FileOperationException
from utils.error_codes import DOC_PARSE_FAILED
from utils.text_utils import clean_text
from utils.logger import get_logger

logger = get_logger(__name__)

# 近似一页的字符数（Word 无真实分页，按内容量切分逻辑页）
CHARS_PER_APPROX_PAGE = 1500


class DocxParser(BaseDocumentParser):
    supported_extensions = [".docx"]

    def parse(self, file_path: str) -> ParsedDocument:
        if not os.path.exists(file_path):
            raise FileOperationException(DOC_PARSE_FAILED, f"文件不存在: {file_path}")

        try:
            from docx import Document
        except ImportError as e:
            raise FileOperationException(
                DOC_PARSE_FAILED, "python-docx 未安装，请执行 pip install python-docx"
            ) from e

        try:
            doc = Document(file_path)
        except Exception as e:
            raise FileOperationException(DOC_PARSE_FAILED, f"DOCX 打开失败: {e}") from e

        blocks: List[str] = []

        # 按文档顺序遍历段落与表格（python-docx 不直接支持顺序遍历 body 元素，
        # 这里用 iter_inner_content 兼容新版本，回退到段落+表格分开处理）
        try:
            from docx.document import Document as _Doc
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            def iter_blocks(parent):
                for child in parent.element.body.iterchildren():
                    if child.tag.endswith("}p"):
                        yield Paragraph(child, parent)
                    elif child.tag.endswith("}tbl"):
                        yield Table(child, parent)

            for block in iter_blocks(doc):
                if isinstance(block, Table):
                    for row in block.rows:
                        cells = [c.text.strip() for c in row.cells]
                        blocks.append(" | ".join(cells))
                else:
                    text = clean_text(block.text)
                    if text:
                        blocks.append(text)
        except Exception:
            # 兜底：仅提取段落
            for para in doc.paragraphs:
                text = clean_text(para.text)
                if text:
                    blocks.append(text)

        full_text = "\n".join(blocks)
        pages = self._split_into_pages(full_text)
        title = os.path.splitext(os.path.basename(file_path))[0]
        return ParsedDocument(
            title=title,
            pages=pages,
            metadata={
                "source": file_path,
                "format": "docx",
                "page_count": len(pages),
            },
        )

    @staticmethod
    def _split_into_pages(full_text: str) -> List[PageText]:
        """按近似字符数把连续文本切分为逻辑页"""
        if not full_text.strip():
            return [PageText(page_number=1, text="")]

        paragraphs = full_text.split("\n")
        pages: List[PageText] = []
        buf: List[str] = []
        buf_len = 0

        for para in paragraphs:
            buf.append(para)
            buf_len += len(para)
            if buf_len >= CHARS_PER_APPROX_PAGE:
                pages.append(PageText(page_number=len(pages) + 1, text="\n".join(buf)))
                buf, buf_len = [], 0

        if buf:
            pages.append(PageText(page_number=len(pages) + 1, text="\n".join(buf)))

        return pages or [PageText(page_number=1, text="")]
