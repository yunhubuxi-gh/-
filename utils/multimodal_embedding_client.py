"""
多模态（图文）嵌入客户端 —— 本地 Chinese-CLIP（modelscope 开源模型，进程内推理）

使用 modelscope 开源的 chinese-clip-vit-large-patch14-336px（默认），把「图片」与「文本」
编码到同一向量空间，支持「用文字描述画面内容 → 召回对应图片」的跨模态语义检索。

设计要点（与 utils/embedding_client 文本 BGE 完全分离）：
- 图片向量存独立集合 kb_{id}_img，不污染文本向量集合 kb_{id}。
- 可选开关：ENABLE_IMAGE_EMBED=false 时本模块返回 None，且「不导入 torch/transformers/modelscope」，
  系统完全退回原文本 RAG 行为（即使未安装相关依赖也不报错）。
- 懒加载：不是服务启动就加载 CLIP；第一次真正处理图片时才下载并加载模型，
  避免服务启动被模型下载卡住。
- 模型下载失败重试 clip_download_retry 次，仍失败则打印清晰警告并关闭图片向量化功能。
- 设备自动检测：优先 cuda；无 NVIDIA GPU 自动降级 cpu，并打印「CPU 运行图片向量化速度较慢」提示。

禁止：密钥/模型名硬编码、引入 Ollama、调用任何外部图片 Embedding API，全部读取 config.settings。
"""
from __future__ import annotations

from typing import List, Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def _resolve_model_name() -> str:
    """解析模型名：优先 CLIP_MODEL_NAME，兼容旧 MULTIMODAL_EMBEDDING_MODEL"""
    name = (settings.clip_model_name or "").strip()
    if not name:
        name = (settings.multimodal_embedding_model or "").strip()
    if not name:
        name = "damo/multi-modal_clip-vit-large-patch14_336_zh"
    return name


def _resolve_device() -> str:
    """解析运行设备：优先 CLIP_DEVICE，兼容旧 MULTIMODAL_EMBEDDING_DEVICE"""
    dev = (settings.clip_device or "").strip().lower()
    if not dev:
        dev = (settings.multimodal_embedding_device or "").strip().lower()
    return dev or "auto"


def _detect_device():
    """自动检测设备：auto 优先 cuda；无 NVIDIA GPU 降级 cpu 并提示"""
    import torch

    configured = _resolve_device()
    if configured == "cuda":
        if torch.cuda.is_available():
            return "cuda"
        logger.warning("CLIP_DEVICE=cuda 但未检测到可用 GPU，降级为 CPU")
        return "cpu"
    if configured == "cpu":
        return "cpu"

    # auto：优先 cuda，无 GPU 降级 cpu
    if torch.cuda.is_available():
        return "cuda"
    logger.info("CPU 运行图片向量化速度较慢（未检测到 NVIDIA GPU）")
    return "cpu"


class MultimodalEmbeddingClient:
    """Chinese-CLIP 图文嵌入客户端（modelscope，本地推理）"""

    def __init__(self, model_name: str | None = None, device: str | None = None):
        import os

        self.model_name = model_name or _resolve_model_name()
        self.device = device or _detect_device()

        # 1. 定位本地 HF 格式目录：
        #    - 若 CLIP_MODEL_NAME 直接指向本地 HF 目录（含 config.json）→ 直接用；
        #    - 否则从 modelscope 下载（带重试），再转换为 HF 格式缓存。
        local_dir = self._prepare_local_dir()

        # 2. 从本地 HF 目录加载（Chinese-CLIP 需专用 ChineseCLIPModel / Processor）
        from transformers import ChineseCLIPModel, ChineseCLIPProcessor

        self._model = ChineseCLIPModel.from_pretrained(local_dir).to(self.device).eval()
        self._processor = ChineseCLIPProcessor.from_pretrained(local_dir)
        self.dimension = int(self._model.config.projection_dim)
        # 推理计数：每处理 clip_gc_interval 张图片做一次完整内存回收（gc + empty_cache）
        self._inference_count = 0
        logger.info(
            f"多模态嵌入客户端初始化完成: model={self.model_name}, "
            f"device={self.device}, dim={self.dimension}"
        )

    def _prepare_local_dir(self) -> str:
        """下载（如需）并把模型整理为可直接加载的 HF 格式目录，返回目录路径"""
        import os

        # 本地目录且已是 HF 格式：直接用
        if os.path.isdir(self.model_name) and os.path.isfile(os.path.join(self.model_name, "config.json")):
            logger.info(f"Chinese-CLIP 使用本地 HF 模型目录: {self.model_name}")
            return self.model_name

        from modelscope import snapshot_download
        from utils.clip_model_loader import convert_modelscope_to_hf

        local_dir = None
        last_err: Optional[Exception] = None
        retry = max(1, int(settings.clip_download_retry))
        for attempt in range(1, retry + 1):
            try:
                local_dir = snapshot_download(self.model_name)
                break
            except Exception as e:
                last_err = e
                logger.warning(
                    f"Chinese-CLIP 模型下载失败（第 {attempt}/{retry} 次）: {self.model_name}, err={e}"
                )
        if local_dir is None:
            raise RuntimeError(
                f"Chinese-CLIP 模型下载失败（已重试 {retry} 次）: {self.model_name}，"
                f"最后错误: {last_err}"
            )

        # 已是 HF 格式（含 config.json）则直接加载，否则转换 modelscope 原始格式
        if os.path.isfile(os.path.join(local_dir, "config.json")):
            return local_dir

        hf_dir = local_dir + "_hf"
        return convert_modelscope_to_hf(local_dir, hf_dir)

    # ---------- 图片嵌入 ----------

    def embed_image(self, image_path: str) -> List[float]:
        return self.embed_images([image_path])[0]

    def embed_images(self, image_paths: List[str]) -> List[List[float]]:
        import torch
        from PIL import Image

        if not image_paths:
            return []
        images = []
        valid_idx = []
        for i, p in enumerate(image_paths):
            try:
                # 用 with 上下文及时关闭文件句柄，convert 出的图像对象稍后统一释放
                with Image.open(p) as im:
                    images.append(im.convert("RGB"))
                valid_idx.append(i)
            except Exception as e:
                logger.warning(f"图片读取失败，跳过该图向量化: {p}, err={e}")
        if not images:
            return []

        inputs = None
        feats = None
        try:
            inputs = self._processor(images=images, return_tensors="pt", padding=True).to(self.device)
            with torch.no_grad():
                feats = self._model.get_image_features(**inputs)
            feats = feats / feats.norm(dim=-1, keepdim=True)
            vecs = feats.cpu().numpy().tolist()
        finally:
            # 及时释放中间 tensor 与图像对象，缓解本地 CLIP 内存泄漏/OOM
            for im in images:
                try:
                    im.close()
                except Exception:
                    pass
            del inputs, feats, images
            self._release_memory()

        # 把成功图片的向量按原位置回填，失败的置空
        result: List[List[float]] = []
        it = iter(vecs)
        for i in range(len(image_paths)):
            if i in valid_idx:
                result.append(next(it))
            else:
                result.append([])
        return result

    def _release_memory(self, force: bool = False) -> None:
        """及时回收内存：每次调用 gc.collect()；每 clip_gc_interval 次做一次完整回收（含 CUDA 缓存）"""
        import gc

        self._inference_count = getattr(self, "_inference_count", 0) + 1
        interval = max(1, int(getattr(settings, "clip_gc_interval", 10) or 10))
        do_full = force or self._inference_count >= interval
        if do_full:
            self._inference_count = 0
        gc.collect()
        if do_full:
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

    # ---------- 文本嵌入（查询侧）----------

    def embed_query(self, query: str) -> List[float]:
        return self.embed_texts([query])[0]

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        import torch

        if not texts:
            return []
        inputs = None
        feats = None
        try:
            inputs = self._processor(text=texts, return_tensors="pt", padding=True, truncation=True).to(self.device)
            with torch.no_grad():
                feats = self._model.get_text_features(**inputs)
            feats = feats / feats.norm(dim=-1, keepdim=True)
            return feats.cpu().numpy().tolist()
        finally:
            del inputs, feats
            self._release_memory()


# ==================== 工厂 ====================
_instance = None
_initialized = False


def get_multimodal_client():
    """
    获取多模态嵌入客户端单例（懒加载，按 provider 分发）。

    provider 取值（config.settings.image_embed_provider）：
    - local ：本地 Chinese-CLIP（modelscope，进程内推理，需要 torch/transformers）
    - doubao：豆包云端多模态向量化（纯 requests，无需本地 GPU / 大模型）

    Returns:
        客户端实例；功能关闭 / 初始化失败时返回 None（调用方需兜底）。
        两种 provider 的客户端都提供 embed_image/embed_images/embed_query/embed_texts
        以及 dimension 属性，接口一致，image_retriever 无需感知差异。
    """
    global _instance, _initialized
    if _initialized:
        return _instance
    _initialized = True

    if not settings.enable_image_embed:
        logger.debug("图片向量化已关闭（ENABLE_IMAGE_EMBED=false）")
        return None

    provider = getattr(settings, "image_embed_provider", "local")

    try:
        if provider == "doubao":
            # 豆包云端：不导入 torch/transformers/modelscope
            from utils.doubao_embedding_client import DoubaoEmbeddingClient
            _instance = DoubaoEmbeddingClient()
        else:
            # 本地 Chinese-CLIP：仅在此分支导入重依赖
            _instance = MultimodalEmbeddingClient()
    except Exception as e:
        logger.warning(
            f"多模态嵌入模型加载失败，图片向量化将不可用（文本业务不受影响）: "
            f"provider={provider}, err={e}"
        )
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
