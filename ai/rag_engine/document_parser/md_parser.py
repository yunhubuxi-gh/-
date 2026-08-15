"""
Markdown / 纯文本 文档解析器

- Markdown：去除常见语法标记（标题 #、加粗、链接等）保留正文
- TXT：直接按文本读取
"""
from __future__ import annotations

import os
import re
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

CHARS_PER_APPROX_PAGE = 1500


class MarkdownParser(BaseDocumentParser):
    """Markdown 与纯文本解析器（.md / .markdown / .txt）"""

    supported_extensions = [".md", ".markdown", ".txt"]

    def parse(self, file_path: str) -> ParsedDocument:
        if not os.path.exists(file_path):
            raise FileOperationException(DOC_PARSE_FAILED, f"文件不存在: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except UnicodeDecodeError:
            # 中文/GBK 编码兜底
            try:
                with open(file_path, "r", encoding="gbk", errors="ignore") as f:
                    raw = f.read()
            except Exception as e:
                raise FileOperationException(DOC_PARSE_FAILED, f"文件读取失败: {e}") from e
        except Exception as e:
            raise FileOperationException(DOC_PARSE_FAILED, f"文件读取失败: {e}") from e

        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".md", ".markdown"):
            text = self._strip_markdown(raw)
        else:
            text = raw

        text = clean_text(text)
        pages = self._split_into_pages(text)
        title = os.path.splitext(os.path.basename(file_path))[0]
        return ParsedDocument(
            title=title,
            pages=pages,
            metadata={
                "source": file_path,
                "format": "md" if ext != ".txt" else "txt",
                "page_count": len(pages),
            },
        )

    # ---------- Markdown 语法清理 ----------

    @staticmethod
    def _strip_markdown(text: str) -> str:
        # 代码块：去掉 ``` 围栏，保留内容
        text = re.sub(r"```[a-zA-Z0-9]*\n?", "", text)
        text = text.replace("```", "")
        # 标题
        text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
        # 图片 ![...](...)
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
        # 链接 [text](url) -> text
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        # 加粗/斜体/删除线
        text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
        text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
        text = re.sub(r"~~(.*?)~~", r"\1", text)
        # 引用块 / 列表符号
        text = re.sub(r"^\s{0,3}(>\s?)", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s{0,3}[-*+]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s{0,3}\d+\.\s+", "", text, flags=re.MULTILINE)
        # 水平分割线
        text = re.sub(r"^\s{0,3}([-*_])\s*(?:\1\s*){2,}$", "", text, flags=re.MULTILINE)
        return text

    @staticmethod
    def _split_into_pages(text: str) -> List[PageText]:
        if not text.strip():
            return [PageText(page_number=1, text="")]
        paragraphs = text.split("\n")
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
