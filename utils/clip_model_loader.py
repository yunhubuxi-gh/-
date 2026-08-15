"""
Chinese-CLIP 本地模型加载器（进程内本地推理，懒加载）

职责：
1. 从 modelscope 下载 chinese-clip-vit-large-patch14-336px（OpenAI-CLIP 原始格式，
   权重键带 ``module.`` 前缀）到本地缓存；
2. 将 modelscope 原始权重转换为 HuggingFace ``transformers`` 的
   ``ChineseCLIPModel`` / ``ChineseCLIPProcessor`` 可加载的 HF 格式，并缓存；
3. 返回可直接 ``ChineseCLIPModel.from_pretrained`` / ``ChineseCLIPProcessor.from_pretrained``
   的本地目录。

转换是幂等的：转换结果落盘到本地缓存目录，第二次起直接复用，不重复转换。
本模块只在 ``ENABLE_IMAGE_EMBED=true`` 且首次处理图片时被调用（懒加载），
转换失败抛异常，由上层 ``MultimodalEmbeddingClient`` 捕获并关闭图片向量化，
不影响文本业务。
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)


def _remap_state_dict(raw: dict) -> dict:
    """modelscope 权重（OpenAI-CLIP 格式，``module.`` 前缀）→ HF ChineseCLIPModel 权重。

    关键差异：
    - 文本侧 ``module.bert.*`` 与 HF ``text_model.*`` 结构 1:1（标准 BERT 层），直接改名；
    - 视觉侧 OpenAI ViT 的 ``attn.in_proj_weight`` 是拼接的 q/k/v，需按 dim0 拆成 3 份；
    - ``text_projection`` / ``visual.proj`` 在 OpenAI 中是 ``nn.Parameter + matmul``（形状
      ``(in, out)``），HF 是 ``nn.Linear``（权重 ``(out, in)``），需转置；
    - ``bert.pooler`` 在 HF ChineseCLIPTextModel 中不存在（``add_pooling_layer=False``），丢弃。
    """
    import torch

    out: dict = {}

    for src_key, val in raw.items():
        k = src_key
        if k.startswith("module."):
            k = k[len("module."):]

        # 丢弃 BERT pooler（HF 文本模型不使用）
        if k.startswith("bert.pooler"):
            continue

        # 文本侧：bert.* → text_model.*（1:1）
        if k.startswith("bert."):
            out["text_model." + k[len("bert."):]] = val.clone()
            continue

        # 文本投影（OpenAI nn.Parameter(matmul) → HF nn.Linear，转置）
        if k == "text_projection":
            out["text_projection.weight"] = val.t().contiguous()
            continue

        if k == "logit_scale":
            out["logit_scale"] = val.reshape(())
            continue

        # 视觉侧固定结构
        if k == "visual.class_embedding":
            out["vision_model.embeddings.class_embedding"] = val.clone()
            continue
        if k == "visual.positional_embedding":
            out["vision_model.embeddings.position_embedding.weight"] = val.clone()
            continue
        if k == "visual.conv1.weight":
            out["vision_model.embeddings.patch_embedding.weight"] = val.clone()
            continue
        if k.startswith("visual.ln_pre"):
            out["vision_model.pre_layrnorm." + k[len("visual.ln_pre."):]] = val.clone()
            continue
        if k.startswith("visual.ln_post"):
            out["vision_model.post_layernorm." + k[len("visual.ln_post."):]] = val.clone()
            continue
        if k == "visual.proj":
            # (in=1024, out=768) → HF Linear.weight (out=768, in=1024)，转置
            out["visual_projection.weight"] = val.t().contiguous()
            continue

        # 视觉 Transformer resblocks → vision_model.encoder.layers
        if k.startswith("visual.transformer.resblocks."):
            rest = k[len("visual.transformer.resblocks."):]  # e.g. "0.attn.in_proj_weight"
            parts = rest.split(".")
            layer_idx = parts[0]
            sub = ".".join(parts[1:])
            hf_prefix = f"vision_model.encoder.layers.{layer_idx}."

            if sub == "attn.in_proj_weight":
                q, kk, v = val.chunk(3, dim=0)
                out[hf_prefix + "self_attn.q_proj.weight"] = q.contiguous()
                out[hf_prefix + "self_attn.k_proj.weight"] = kk.contiguous()
                out[hf_prefix + "self_attn.v_proj.weight"] = v.contiguous()
            elif sub == "attn.in_proj_bias":
                q, kk, v = val.chunk(3, dim=0)
                out[hf_prefix + "self_attn.q_proj.bias"] = q.contiguous()
                out[hf_prefix + "self_attn.k_proj.bias"] = kk.contiguous()
                out[hf_prefix + "self_attn.v_proj.bias"] = v.contiguous()
            elif sub == "attn.out_proj.weight":
                out[hf_prefix + "self_attn.out_proj.weight"] = val.clone()
            elif sub == "attn.out_proj.bias":
                out[hf_prefix + "self_attn.out_proj.bias"] = val.clone()
            elif sub == "ln_1.weight":
                out[hf_prefix + "layer_norm1.weight"] = val.clone()
            elif sub == "ln_1.bias":
                out[hf_prefix + "layer_norm1.bias"] = val.clone()
            elif sub == "mlp.c_fc.weight":
                out[hf_prefix + "mlp.fc1.weight"] = val.clone()
            elif sub == "mlp.c_fc.bias":
                out[hf_prefix + "mlp.fc1.bias"] = val.clone()
            elif sub == "mlp.c_proj.weight":
                out[hf_prefix + "mlp.fc2.weight"] = val.clone()
            elif sub == "mlp.c_proj.bias":
                out[hf_prefix + "mlp.fc2.bias"] = val.clone()
            elif sub == "ln_2.weight":
                out[hf_prefix + "layer_norm2.weight"] = val.clone()
            elif sub == "ln_2.bias":
                out[hf_prefix + "layer_norm2.bias"] = val.clone()
            else:
                raise ValueError(f"未识别的视觉键: {src_key}")
            continue

        raise ValueError(f"未识别的权重键: {src_key}")

    return out


def convert_modelscope_to_hf(src_dir: str, dst_dir: str) -> str:
    """将 modelscope 下载的 Chinese-CLIP 原始权重转换为 HF 格式并缓存。

    返回 HF 格式目录路径。幂等：``dst_dir/_conversion_done`` 存在则直接返回。
    """
    import torch
    from transformers import ChineseCLIPConfig, ChineseCLIPModel
    from transformers import ChineseCLIPImageProcessor, BertTokenizer

    sentinel = os.path.join(dst_dir, "_conversion_done")
    if os.path.isfile(sentinel):
        return dst_dir

    os.makedirs(dst_dir, exist_ok=True)

    with open(os.path.join(src_dir, "text_model_config.json"), encoding="utf-8") as f:
        tcfg = json.load(f)
    with open(os.path.join(src_dir, "vision_model_config.json"), encoding="utf-8") as f:
        vcfg = json.load(f)

    projection_dim = vcfg.get("embed_dim", 768)
    vision_hidden = vcfg.get("vision_width", 1024)
    num_heads = vision_hidden // 64  # ViT 标准 head_dim=64
    native_resolution = vcfg.get("image_resolution", 336)

    cfg = ChineseCLIPConfig(
        text_config=dict(
            vocab_size=tcfg.get("vocab_size", 21128),
            hidden_size=tcfg.get("text_hidden_size", 768),
            num_hidden_layers=tcfg.get("text_num_hidden_layers", 12),
            num_attention_heads=tcfg.get("text_num_attention_heads", 12),
            intermediate_size=tcfg.get("text_intermediate_size", 3072),
            hidden_act=tcfg.get("text_hidden_act", "gelu"),
            hidden_dropout_prob=tcfg.get("text_hidden_dropout_prob", 0.1),
            attention_probs_dropout_prob=tcfg.get("text_attention_probs_dropout_prob", 0.1),
            max_position_embeddings=tcfg.get("text_max_position_embeddings", 512),
            type_vocab_size=tcfg.get("text_type_vocab_size", 2),
            initializer_range=tcfg.get("text_initializer_range", 0.02),
        ),
        vision_config=dict(
            hidden_size=vision_hidden,
            num_hidden_layers=vcfg.get("vision_layers", 24),
            num_attention_heads=num_heads,
            intermediate_size=vision_hidden * 4,
            patch_size=vcfg.get("vision_patch_size", 14),
            image_size=native_resolution,
            hidden_act="gelu",
            initializer_range=0.02,
        ),
        projection_dim=projection_dim,
    )

    model = ChineseCLIPModel(cfg)

    # 读取原始权重
    ckpt_path = os.path.join(src_dir, "pytorch_model.bin")
    raw = torch.load(ckpt_path, map_location="cpu")
    if isinstance(raw, dict) and "state_dict" in raw:
        raw = raw["state_dict"]

    remapped = _remap_state_dict(raw)

    # 校验映射完整性 + 形状
    hf_sd = model.state_dict()
    hf_keys = set(hf_sd.keys())
    remap_keys = set(remapped.keys())
    missing = hf_keys - remap_keys
    extra = remap_keys - hf_keys
    if missing or extra:
        raise ValueError(
            f"Chinese-CLIP 权重映射不完整：missing={sorted(missing)[:20]} extra={sorted(extra)[:20]}"
        )
    for k in hf_keys:
        if remapped[k].shape != hf_sd[k].shape:
            raise ValueError(
                f"Chinese-CLIP 权重形状不匹配 {k}: {tuple(remapped[k].shape)} vs {tuple(hf_sd[k].shape)}"
            )

    model.load_state_dict(remapped, strict=True)

    # 保存模型 + 图像处理器 + 分词器
    model.save_pretrained(dst_dir)
    # 注意：Chinese-CLIP 预处理为「等比例拉伸到固定 336×336（BICUBIC）+ CLIP 归一化」，无中心裁剪。
    # 用 {"height","width"} 精确尺寸（而非 {"shortest_edge"}），可规避 transformers 4.46 中
    # ChineseCLIPImageProcessor 对 shortest_edge 的 KeyError 兼容性缺陷。
    ChineseCLIPImageProcessor(
        size={"height": native_resolution, "width": native_resolution},
        do_center_crop=False,
        do_rescale=True,
        do_normalize=True,
        image_mean=[0.48145466, 0.4578275, 0.40821073],
        image_std=[0.26862954, 0.26130258, 0.27577711],
    ).save_pretrained(dst_dir)
    tokenizer = BertTokenizer(vocab_file=os.path.join(src_dir, "vocab.txt"))
    tokenizer.model_max_length = 512  # Chinese-CLIP 文本最大位置编码 512，避免截断告警
    tokenizer.save_pretrained(dst_dir)

    with open(sentinel, "w", encoding="utf-8") as f:
        f.write("done")

    logger.info("Chinese-CLIP 已转换为 HF 格式并缓存到 %s", dst_dir)
    return dst_dir
