"""
PDF 文档解析器（PyMuPDF / fitz）

解析策略：
1. 优先使用 PyMuPDF 提取文本层
2. 若某页文本过少（疑似扫描件），渲染为图片调用 OCR 识别
3. OCR 失败时优雅降级（保留空文本 / 已提取部分），不中断整篇解析
4. 解析结束后过滤页眉页脚等重复噪声
"""
from __future__ import annotations

import os
import re
from typing import List, Optional

from ai.rag_engine.document_parser.base_parser import (
    BaseDocumentParser,
    ParsedDocument,
    PageText,
    ExtractedImage,
)
from utils.exceptions import FileOperationException
from utils.error_codes import DOC_PARSE_FAILED
from utils.text_utils import clean_text
from utils.logger import get_logger

logger = get_logger(__name__)

# 单页文本低于此字符数视为「扫描件」，触发 OCR
MIN_TEXT_CHARS_FOR_TEXT_LAYER = 20


class PDFParser(BaseDocumentParser):
    supported_extensions = [".pdf"]

    def __init__(self, ocr_engine=None):
        """
        Args:
            ocr_engine: OCR 引擎实例，缺省时懒加载 utils.ocr_engine.get_ocr_engine()
        """
        self._ocr_engine = ocr_engine

    def _get_ocr_engine(self):
        if self._ocr_engine is None:
            from utils.ocr_engine import get_ocr_engine
            self._ocr_engine = get_ocr_engine()
        return self._ocr_engine

    def parse(self, file_path: str) -> ParsedDocument:
        if not os.path.exists(file_path):
            raise FileOperationException(DOC_PARSE_FAILED, f"文件不存在: {file_path}")

        try:
            import fitz  # PyMuPDF
        except ImportError as e:
            raise FileOperationException(
                DOC_PARSE_FAILED, "PyMuPDF 未安装，请执行 pip install pymupdf"
            ) from e

        try:
            doc = fitz.open(file_path)
        except Exception as e:
            raise FileOperationException(DOC_PARSE_FAILED, f"PDF 打开失败: {e}") from e

        pages: List[PageText] = []
        images: List[ExtractedImage] = []
        try:
            for i, page in enumerate(doc):
                page_number = i + 1
                text = clean_text(page.get_text("text") or "")
                if len(text.strip()) < MIN_TEXT_CHARS_FOR_TEXT_LAYER:
                    # 疑似扫描件，尝试 OCR
                    ocr_text = self._ocr_page(page, page_number)
                    if ocr_text.strip():
                        text = ocr_text
                    else:
                        logger.warning(
                            f"PDF 第 {page_number} 页无文本层且 OCR 不可用，已跳过"
                        )
                pages.append(PageText(page_number=page_number, text=text))

                # 提取本页内嵌图片（供多模态向量化）
                images.extend(self._extract_page_images(page, page_number))
        finally:
            doc.close()

        pages = self._filter_header_footer_noise(pages)
        title = os.path.splitext(os.path.basename(file_path))[0]
        logger.info(f"PDF 解析完成: 提取到 {len(images)} 张内嵌图片")
        return ParsedDocument(
            title=title,
            pages=pages,
            images=images,
            metadata={
                "source": file_path,
                "format": "pdf",
                "page_count": len(pages),
            },
        )

    def _extract_page_images(self, page, page_number: int) -> List[ExtractedImage]:
        """提取单页内嵌图片（PyMuPDF），失败优雅跳过"""
        results: List[ExtractedImage] = []
        try:
            image_list = page.get_images(full=True) or []
        except Exception as e:
            logger.warning(f"PDF 第 {page_number} 页读取图片列表失败: {e}")
            return results

        for idx, img_info in enumerate(image_list):
            try:
                xref = img_info[0]
                ext = (img_info[8] or "png").lower().replace("jpeg", "jpg")
                info = page.parent.extract_image(xref)
                if not info or not info.get("image"):
                    continue
                results.append(ExtractedImage(
                    page_number=page_number,
                    image_bytes=info["image"],
                    ext=ext,
                    index=idx,
                ))
            except Exception as e:
                logger.warning(f"PDF 第 {page_number} 页图片提取失败: {e}")
                continue
        return results

    def _ocr_page(self, page, page_number: int) -> str:
        """渲染单页为图片并调用 OCR，失败时返回空字符串（优雅降级）"""
        engine = self._get_ocr_engine()
        if engine is None:
            return ""
        try:
            # 渲染为 PNG 字节流
            pix = page.get_pixmap(dpi=150)
            image_bytes = pix.tobytes("png")
            return clean_text(engine.recognize_image_bytes(image_bytes) or "")
        except Exception as e:
            logger.warning(f"PDF 第 {page_number} 页 OCR 失败: {e}")
            return ""

    # ---------- 页眉页脚噪声过滤 ----------

    @staticmethod
    def _filter_header_footer_noise(pages: List[PageText]) -> List[PageText]:
        """
        过滤页眉页脚噪声：
        - 移除纯页码行（如 "1"、"第 1 页"、"Page 1"）
        - 移除在多页重复出现且位于页首/页尾的行（典型页眉/页脚）
        """
        if len(pages) <= 2:
            return pages

        # 统计每一「行」出现的页数
        line_freq: dict[str, int] = {}
        for p in pages:
            seen = set()
            for line in p.text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line in seen:
                    continue
                seen.add(line)
                line_freq[line] = line_freq.get(line, 0) + 1

        threshold = max(2, int(len(pages) * 0.6))
        noise_lines = {
            line for line, cnt in line_freq.items()
            if cnt >= threshold and PDFParser._is_noise_line(line)
        }

        if not noise_lines:
            return pages

        filtered = []
        for p in pages:
            lines = p.text.split("\n")
            kept = [ln for ln in lines if ln.strip() not in noise_lines]
            filtered.append(PageText(page_number=p.page_number, text="\n".join(kept)))
        return filtered

    @staticmethod
    def _is_noise_line(line: str) -> bool:
        """判断单行是否为页码/页眉页脚类噪声"""
        s = line.strip()
        # 纯数字（页码）
        if re.fullmatch(r"\d{1,4}", s):
            return True
        # 常见页码格式
        if re.fullmatch(r"(第\s*\d+\s*页|page\s*\d+|\d+\s*/\s*\d+)", s, re.IGNORECASE):
            return True
        # 过短（1~3 字符）且非汉字实词，多为装饰符号
        if len(s) <= 3 and not re.search(r"[一-鿿]", s):
            return True
        return False
