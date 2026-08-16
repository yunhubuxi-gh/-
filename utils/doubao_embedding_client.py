"""
豆包（火山方舟）云端多模态向量化客户端

通过火山方舟 Ark 的 OpenAI 兼容 embeddings 接口，把「文本」与「图片」编码到
**同一向量空间**，支持「文字描述 → 召回图片」的跨模态检索。

与本地 Chinese-CLIP（utils/multimodal_embedding_client.MultimodalEmbeddingClient）二选一，
由 config.settings.image_embed_provider 决定（local / doubao）。

设计要点：
- 纯 `requests` 实现，**不导入 torch / transformers / modelscope**，
  因此 provider=doubao 时完全不需要本地 GPU / 大体积模型依赖。
- 每张图片独立 try-except，单张失败只跳过该图、返回空向量，不影响整体。
- 图片先压缩（等比缩放长边到 doubao_image_max_side + JPEG 质量 85）再 base64 上传，
  显著降低图片 token 消耗（豆包图片按像素面积计费，压缩越狠越省钱）。
- 限流/超时自动重试（doubao_max_retry 次，指数退避），豆包图片 embedding 约 15 张/秒。
- 接口约束：入库与查询必须用同一模型、同一维度（doubao_image_embed_dim），否则向量不可比。

禁止：密钥/模型名硬编码；全部读取 config.settings。
"""
from __future__ import annotations

import base64
import io
import time
from typing import List, Optional

import requests

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class DoubaoEmbeddingClient:
    """豆包多模态向量化客户端（云端 API，图文同空间）"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
    ):
        self.api_key = (api_key or settings.doubao_api_key).strip()
        if not self.api_key:
            raise RuntimeError("豆包 API Key 未配置（DOUBAO_API_KEY），无法初始化云端图片向量化")

        self.base_url = (base_url or settings.doubao_base_url).rstrip("/")
        self.model = model or settings.doubao_embedding_model
        self.dimension = int(dimension or settings.doubao_image_embed_dim)
        self.timeout = settings.doubao_timeout
        self.max_retry = max(1, int(settings.doubao_max_retry))
        self.image_max_side = int(settings.doubao_image_max_side)

        logger.info(
            f"豆包多模态向量化客户端初始化: model={self.model}, dim={self.dimension}, "
            f"base_url={self.base_url}, image_max_side={self.image_max_side}"
        )

    # ---------- 底层调用 ----------

    def _request(self, payload: dict) -> dict:
        """发送 embeddings 请求，带限流/超时重试

        豆包多模态向量化走专用端点 /embeddings/multimodal（非 OpenAI 的 /embeddings）。
        base_url 说明：
          - 标准方舟（按量付费）    : https://ark.cn-beijing.volces.com/api/v3
          - Agent Plan 个人版（套餐）: https://ark.cn-beijing.volces.com/api/plan/v3（含 /plan，勿混用）
        """
        url = f"{self.base_url}/embeddings/multimodal"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retry + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
                # 4xx 通常不是重试能解决的（鉴权/参数错误），直接抛，避免浪费重试与额度
                if 400 <= resp.status_code < 500:
                    raise RuntimeError(
                        f"豆包接口返回 {resp.status_code}: {resp.text[:300]}"
                    )
                # 429 / 5xx：限流或服务端错误，退避重试
                last_err = RuntimeError(f"豆包接口返回 {resp.status_code}: {resp.text[:200]}")
            except (requests.RequestException, RuntimeError) as e:
                last_err = e
                # 4xx 鉴权/参数错误不重试
                if isinstance(e, RuntimeError) and "豆包接口返回 4" in str(e):
                    raise
            if attempt < self.max_retry:
                sleep = min(2 ** attempt, 8)
                logger.warning(f"豆包调用失败，{sleep}s 后重试（{attempt}/{self.max_retry}）: {last_err}")
                time.sleep(sleep)
        raise RuntimeError(f"豆包向量化调用失败（已重试 {self.max_retry} 次）: {last_err}")

    def _call_embeddings(self, inputs: List[dict]) -> List[List[float]]:
        """调用 embeddings 接口，返回与 inputs 对齐的向量列表（失败项为 []）

        注意：豆包 Agent Plan 的 /embeddings/multimodal 返回结构与 OpenAI 不同——
        单输入时 data 是对象 {"embedding":[...]}，多输入时才是数组 [{"index":i,...}]。
        这里统一兼容两种形态，避免按 list 遍历 dict 时报错。
        """
        payload = {
            "model": self.model,
            "input": inputs,
            "dimensions": self.dimension,
        }
        resp = self._request(payload)
        data = resp.get("data", [])
        if isinstance(data, dict):
            data = [data]
        # 按 index 回填；无 index 字段时按顺序（单输入对象即此情况）
        vecs: List[List[float]] = [[] for _ in inputs]
        for i, it in enumerate(data):
            if not isinstance(it, dict):
                continue
            idx = it.get("index", i)
            emb = it.get("embedding") or []
            if 0 <= idx < len(vecs):
                vecs[idx] = [float(x) for x in emb]
        return vecs

    # ---------- 图片嵌入 ----------

    def embed_image(self, image_path: str) -> List[float]:
        return self.embed_images([image_path])[0]

    def embed_images(self, image_paths: List[str]) -> List[List[float]]:
        """批量图片向量化（逐张 try-except，失败返回空向量）"""
        result: List[List[float]] = []
        for p in image_paths:
            try:
                b64 = self._image_to_base64(p)
                vecs = self._call_embeddings([{
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                }])
                result.append(vecs[0] if vecs and vecs[0] else [])
            except Exception as e:
                logger.warning(f"豆包图片向量化失败，跳过: {p}, err={e}")
                result.append([])
        return result

    # ---------- 文本嵌入（查询侧）----------

    def embed_query(self, query: str) -> List[float]:
        return self.embed_texts([query])[0]

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """文本向量化（与图片同空间，用于查询侧跨模态召回）"""
        inputs = [{"type": "text", "text": t} for t in texts]
        try:
            return self._call_embeddings(inputs)
        except Exception as e:
            logger.warning(f"豆包文本向量化失败: {e}")
            return [[] for _ in texts]

    # ---------- 图片压缩（省钱关键）----------

    def _image_to_base64(self, image_path: str) -> str:
        """读取图片 → 等比压缩长边 + JPEG 质量 85 → base64，降低 token 消耗"""
        from PIL import Image

        with Image.open(image_path) as im:
            im = im.convert("RGB")
            w, h = im.size
            longest = max(w, h)
            if longest > self.image_max_side:
                ratio = self.image_max_side / longest
                im = im.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("ascii")
