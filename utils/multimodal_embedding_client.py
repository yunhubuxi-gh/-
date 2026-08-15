"""
多模态（图文）嵌入客户端

使用本地 Chinese-CLIP 模型（transformers 加载），把「图片」与「文本」编码到同一向量空间，
从而支持「用文字描述画面内容 → 召回对应图片」的跨模态语义检索。

设计要点：
- 与 utils/embedding_client（文本 BGE）完全分离：文本 RAG 沿用 BGE，图片向量化走本模块。
- 图片向量存独立集合（kb_{id}_img），不污染文本向量集合。
- 可选开关：ENABLE_IMAGE_EMBED=false 时本模块返回 None，系统完全退回原文本 RAG 行为。
- 大图预处理压缩（PIL 缩边），避免显存/接口报错。
- 模型加载失败时优雅降级返回 None，不中断主链路。

禁止：密钥/模型名硬编码，全部读取 config.settings。
"""
from __future__ import annotations

from typing import List, Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class MultimodalEmbeddingClient:
    """Chinese-CLIP 图文嵌入客户端（本地）"""

    def __init__(self, model_name: str | None = None, device: str | None = None):
        import torch
        # Chinese-CLIP 是独立架构（config 内为 ChineseCLIPTextModel），
        # 必须用 transformers 的 ChineseCLIPModel / ChineseCLIPProcessor 加载，
        # 不能用通用 CLIPModel / CLIPProcessor（后者绑定英文 BPE tokenizer，会加载失败）。
        from transformers import ChineseCLIPModel, ChineseCLIPProcessor

        self.model_name = model_name or settings.multimodal_embedding_model
        self.device = (device or settings.multimodal_embedding_device or
                       ("cuda" if torch.cuda.is_available() else "cpu"))
        self.max_side = settings.image_max_side

        self._model = ChineseCLIPModel.from_pretrained(self.model_name).to(self.device).eval()
        self._processor = ChineseCLIPProcessor.from_pretrained(self.model_name)
        self.dimension = self._model.config.projection_dim
        logger.info(
            f"多模态嵌入客户端初始化完成: model={self.model_name}, "
            f"device={self.device}, dim={self.dimension}"
        )

    # ---------- 预处理 ----------

    def _preprocess_image(self, image_path: str):
        """读取并压缩图片，返回 PIL.Image（RGB）"""
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        # 长边缩放，避免大图
        w, h = img.size
        longest = max(w, h)
        if longest > self.max_side:
            ratio = self.max_side / longest
            img = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
        return img

    # ---------- 图片嵌入 ----------

    def embed_image(self, image_path: str) -> List[float]:
        return self.embed_images([image_path])[0]

    def embed_images(self, image_paths: List[str]) -> List[List[float]]:
        import torch
        if not image_paths:
            return []
        images = [self._preprocess_image(p) for p in image_paths]
        inputs = self._processor(images=images, return_tensors="pt", padding=True).to(self.device)
        with torch.no_grad():
            feats = self._model.get_image_features(**inputs)
        feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy().tolist()

    # ---------- 文本嵌入（查询侧）----------

    def embed_query(self, query: str) -> List[float]:
        return self.embed_texts([query])[0]

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        import torch
        if not texts:
            return []
        inputs = self._processor(text=texts, return_tensors="pt", padding=True, truncation=True).to(self.device)
        with torch.no_grad():
            feats = self._model.get_text_features(**inputs)
        feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy().tolist()


# ==================== 工厂 ====================
_instance: Optional[MultimodalEmbeddingClient] = None
_initialized = False


def get_multimodal_client() -> Optional[MultimodalEmbeddingClient]:
    """
    获取多模态嵌入客户端单例。

    Returns:
        客户端实例；功能关闭 / 初始化失败时返回 None（调用方需兜底）。
    """
    global _instance, _initialized
    if _initialized:
        return _instance
    _initialized = True

    if not settings.enable_image_embed:
        logger.debug("图片向量化已关闭（ENABLE_IMAGE_EMBED=false）")
        return None
    if not settings.multimodal_embedding_model:
        logger.warning("未配置 MULTIMODAL_EMBEDDING_MODEL，图片向量化不可用")
        return None

    try:
        _instance = MultimodalEmbeddingClient()
    except Exception as e:
        logger.warning(f"多模态嵌入模型加载失败，图片向量化将不可用: {e}")
        _instance = None
    return _instance


def is_multimodal_available() -> bool:
    """多模态图片向量化是否可用"""
    return get_multimodal_client() is not None


def reset_multimodal_client() -> None:
    """重置（测试用）"""
    global _instance, _initialized
    _instance = None
    _initialized = False
