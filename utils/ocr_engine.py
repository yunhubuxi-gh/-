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
        # PaddleOCR 3.x 已移除 use_angle_cls / show_log 参数。
        # 用 mobile 版模型 + 关闭文档矫正/方向分类/文本行方向等预处理，大幅提速：
        # server 版每页约 80s，mobile 版 + 关预处理可降到每页数秒。
        self._ocr = PaddleOCR(
            lang=lang,
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        logger.info(f"PaddleOCR 引擎初始化完成: lang={lang}（mobile 模型，关闭文档矫正/方向分类）")

    def recognize_image(self, image_path: str) -> str:
        result = self._ocr.predict(image_path)
        return self._extract_text(result)

    def recognize_image_bytes(self, image_bytes: bytes) -> str:
        import numpy as np
        import cv2
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        result = self._ocr.predict(img)
        return self._extract_text(result)

    def _extract_text(self, ocr_result) -> str:
        """从 PaddleOCR 结果中提取文本。

        PaddleOCR 3.x 的 predict() 返回 list[OCRResult]；OCRResult 是 dict-like 对象，
        其 .json 形如 {"res": {"rec_texts": [...], "rec_scores": [...]}}。
        """
        if not ocr_result:
            return ""
        items = ocr_result if isinstance(ocr_result, (list, tuple)) else [ocr_result]
        texts: List[str] = []
        for item in items:
            if item is None:
                continue
            try:
                j = item.json
                if not isinstance(j, dict):
                    j = item.get("res", {}) if hasattr(item, "get") else {}
            except Exception:
                j = {}
            inner = j.get("res", {}) if isinstance(j, dict) else {}
            if isinstance(inner, dict):
                texts.extend(str(t) for t in (inner.get("rec_texts") or []) if t)
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
_init_failed: bool = False
_lock = None  # 延迟创建线程锁，避免导入期开销


def _get_lock():
    global _lock
    if _lock is None:
        import threading
        _lock = threading.Lock()
    return _lock


def get_ocr_engine() -> Optional[BaseOCREngine]:
    """
    获取 OCR 引擎单例。
    如果 OCR 未启用或初始化失败，返回 None，调用方需做兜底处理。

    注意：PaddleOCR 底层 PDX 只允许初始化一次，初始化失败后再次 new 会抛
    「PDX has already been initialized」，故失败后记住状态，后续直接返回 None，
    避免每处理一页就重复初始化、刷屏日志、浪费性能。
    """
    global _instance, _init_failed

    if not settings.ocr_enabled:
        logger.debug("OCR 未启用（OCR_ENABLED=false）")
        return None

    if _instance is not None:
        return _instance

    if _init_failed:
        return None

    with _get_lock():
        # 双重检查：拿锁期间可能已被其他线程初始化
        if _instance is not None:
            return _instance
        if _init_failed:
            return None

        try:
            engine_type = settings.ocr_engine
            if engine_type == "paddleocr":
                _instance = PaddleOCREngine()
            elif engine_type == "tesseract":
                _instance = TesseractEngine()
            else:
                logger.warning(f"未知 OCR 引擎: {engine_type}，OCR 将不可用")
                _init_failed = True
                return None
            return _instance
        except Exception as e:
            _init_failed = True
            logger.warning(f"OCR 引擎初始化失败: {e}，OCR 功能将不可用（本次进程内不再重试）")
            return None


def is_ocr_available() -> bool:
    """检查 OCR 是否可用"""
    return get_ocr_engine() is not None
