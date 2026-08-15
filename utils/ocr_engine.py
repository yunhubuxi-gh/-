"""
OCR 引擎封装
支持 PaddleOCR（推荐，中文效果好）和 Tesseract 两种后端。
主要用于扫描版 PDF 的文字提取。

设计：OCR 是可选组件，若未安装则给出友好提示，不影响其他功能。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class OCRResult:
    """OCR 单页识别结果"""

    def __init__(
        self,
        page_number: int,
        text: str,
        lines: Optional[List[Tuple[str, float]]] = None,  # [(文本, 置信度)]
    ):
        self.page_number = page_number
        self.text = text
        self.lines = lines or []

    def __repr__(self) -> str:
        return f"OCRResult(page={self.page_number}, chars={len(self.text)})"


class BaseOCREngine(ABC):
    """OCR 引擎抽象基类"""

    @abstractmethod
    def recognize_image(self, image_path: str) -> str:
        """识别单张图片，返回文本"""
        ...

    @abstractmethod
    def recognize_image_bytes(self, image_bytes: bytes) -> str:
        """识别图片字节流，返回文本"""
        ...


class PaddleOCREngine(BaseOCREngine):
    """PaddleOCR 引擎（推荐中文场景使用）"""

    def __init__(self):
        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise ImportError(
                "paddleocr 未安装，请执行 pip install paddleocr paddlepaddle"
            ) from e

        lang = settings.ocr_lang
        # use_angle_cls=True 支持倾斜文本检测
        self._ocr = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
        logger.info(f"PaddleOCR 引擎初始化完成: lang={lang}")

    def recognize_image(self, image_path: str) -> str:
        result = self._ocr.ocr(image_path, cls=True)
        return self._extract_text(result)

    def recognize_image_bytes(self, image_bytes: bytes) -> str:
        import numpy as np
        import cv2
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        result = self._ocr.ocr(img, cls=True)
        return self._extract_text(result)

    def _extract_text(self, ocr_result) -> str:
        """从 PaddleOCR 结果中提取文本"""
        if not ocr_result:
            return ""
        # PaddleOCR 返回结构：[[ [box, (text, score)], ... ]]
        texts = []
        for page in ocr_result:
            if page is None:
                continue
            for line in page:
                if len(line) >= 2:
                    text = line[1][0]
                    texts.append(text)
        return "\n".join(texts)


class TesseractEngine(BaseOCREngine):
    """Tesseract OCR 引擎（需本地安装 tesseract 可执行文件）"""

    def __init__(self):
        try:
            import pytesseract
            from PIL import Image  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "pytesseract 未安装，请执行 pip install pytesseract pillow，"
                "并确保系统安装了 tesseract 可执行程序"
            ) from e

        self._pytesseract = pytesseract
        self.lang = "chi_sim+eng" if settings.ocr_lang.startswith("ch") else "eng"
        logger.info(f"Tesseract OCR 引擎初始化完成: lang={self.lang}")

    def recognize_image(self, image_path: str) -> str:
        from PIL import Image
        img = Image.open(image_path)
        return self._pytesseract.image_to_string(img, lang=self.lang)

    def recognize_image_bytes(self, image_bytes: bytes) -> str:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        return self._pytesseract.image_to_string(img, lang=self.lang)


# ==================== 工厂函数 ====================
_instance: Optional[BaseOCREngine] = None


def get_ocr_engine() -> Optional[BaseOCREngine]:
    """
    获取 OCR 引擎单例。
    如果 OCR 未启用或初始化失败，返回 None，调用方需做兜底处理。
    """
    global _instance

    if not settings.ocr_enabled:
        logger.debug("OCR 未启用（OCR_ENABLED=false）")
        return None

    if _instance is not None:
        return _instance

    try:
        engine_type = settings.ocr_engine
        if engine_type == "paddleocr":
            _instance = PaddleOCREngine()
        elif engine_type == "tesseract":
            _instance = TesseractEngine()
        else:
            logger.warning(f"未知 OCR 引擎: {engine_type}，OCR 将不可用")
            return None
        return _instance
    except Exception as e:
        logger.warning(f"OCR 引擎初始化失败: {e}，OCR 功能将不可用")
        return None


def is_ocr_available() -> bool:
    """检查 OCR 是否可用"""
    return get_ocr_engine() is not None
