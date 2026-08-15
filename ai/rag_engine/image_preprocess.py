"""
图片预处理工具模块

职责（图片向量化前的本地预处理，进程内完成，不依赖任何外部服务）：
1. 过滤极小无效图片（边长低于 clip_min_image_side 直接丢弃，避免噪声图进入向量库）
2. 大图等比例缩放压缩（长边不超过 clip_max_image_side，防止 Chinese-CLIP 推理 OOM）
3. 保存处理后的图片副本到上传资源目录（原始图片另存，副本供 CLIP 向量化）

设计要点：
- 每张图片的处理都返回 (状态, 结果/错误信息)，绝不抛出异常打断调用方循环；
  调用方对单张图片异常只跳过该图片，不影响文档整体导入。
- 全部阈值 / 开关读取 config.settings，禁止硬编码。
- 本模块不导入 torch / transformers / modelscope（仅用 PIL），
  保证 ENABLE_IMAGE_EMBED=false 时即使缺少 CLIP 依赖也不会报错。
"""
from __future__ import annotations

from typing import Optional, Tuple

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def preprocess_image(
    image_bytes: bytes,
    output_path: str,
    max_side: Optional[int] = None,
    min_side: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    预处理单张图片：过滤极小图 + 等比例缩放 + 落盘副本。

    Args:
        image_bytes: 图片原始字节
        output_path: 处理后副本的落盘绝对路径
        max_side: 最大边长（缺省取 settings.clip_max_image_side）
        min_side: 最小边长（缺省取 settings.clip_min_image_side）

    Returns:
        (是否成功, 结果说明/错误信息)。失败时调用方应跳过该图片，不中断整体流程。
    """
    max_side = max_side if max_side is not None else settings.clip_max_image_side
    min_side = min_side if min_side is not None else settings.clip_min_image_side

    try:
        from PIL import Image
    except Exception as e:
        return False, f"PIL 未安装，无法预处理图片: {e}"

    try:
        img = Image.open(__import__("io").BytesIO(image_bytes))
        img.load()
    except Exception as e:
        return False, f"图片读取失败（可能已损坏）: {e}"

    try:
        w, h = img.size
        # 1. 过滤极小无效图片（图标/噪点，低于最小边长直接丢弃）
        if w < min_side or h < min_side:
            return False, f"图片过小（{w}x{h} < {min_side}px），过滤无效图片"

        # 2. 等比例缩放压缩（长边不超过 max_side）
        longest = max(w, h)
        if longest > max_side:
            ratio = max_side / longest
            new_size = (max(1, int(w * ratio)), max(1, int(h * ratio)))
            img = img.resize(new_size, Image.LANCZOS)

        # 3. 统一转 RGB（丢弃 alpha 通道，CLIP 输入需 3 通道）
        if img.mode != "RGB":
            img = img.convert("RGB")

        # 4. 落盘副本（PNG，避免二次压缩损失）
        img.save(output_path, format="PNG")
        return True, f"预处理完成 {w}x{h} -> {img.size[0]}x{img.size[1]}"
    except Exception as e:
        return False, f"图片预处理失败: {e}"
