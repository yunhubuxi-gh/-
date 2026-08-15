"""
图片文件解析器（png / jpg / jpeg）

图片走「双通道」处理：
1. 文本通道：调用 OCR 识别图片内文字 → 生成文本 chunk → 文本 BGE 向量化（复用原文本 RAG）
2. 图片通道：原始图片 → 多模态 Embedding 向量化（由上层 document_service 触发）

本解析器只负责「文本通道」的 OCR 文字提取，返回 1 页 ParsedDocument（OCR 文本）。
OCR 不可用时优雅降级（返回空文本），不中断图片的「图片通道」向量化。
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


class ImageParser(BaseDocumentParser):
    supported_extensions = [".png", ".jpg", ".jpeg"]

    def __init__(self, ocr_engine=None):
        self._ocr_engine = ocr_engine

    def _get_ocr_engine(self):
        if self._ocr_engine is None:
            from utils.ocr_engine import get_ocr_engine
            self._ocr_engine = get_ocr_engine()
        return self._ocr_engine

    def parse(self, file_path: str) -> ParsedDocument:
        if not os.path.exists(file_path):
            raise FileOperationException(DOC_PARSE_FAILED, f"文件不存在: {file_path}")

        # 读取图片字节
        try:
            with open(file_path, "rb") as f:
                image_bytes = f.read()
        except OSError as e:
            raise FileOperationException(DOC_PARSE_FAILED, f"图片读取失败: {e}") from e

        # OCR 识别图片内文字（失败优雅降级为空文本）
        ocr_text = ""
        engine = self._get_ocr_engine()
        if engine is not None:
            try:
                ocr_text = clean_text(engine.recognize_image_bytes(image_bytes) or "")
            except Exception as e:
                logger.warning(f"图片 OCR 失败（不影响图片向量化）: {e}")

        title = os.path.splitext(os.path.basename(file_path))[0]
        logger.info(f"图片解析完成: {title}, ocr_chars={len(ocr_text)}")
        return ParsedDocument(
            title=title,
            pages=[PageText(page_number=1, text=ocr_text)],
            metadata={
                "source": file_path,
                "format": "image",
                "page_count": 1,
                "ocr_chars": len(ocr_text),
            },
        )
