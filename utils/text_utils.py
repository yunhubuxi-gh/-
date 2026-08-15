"""
文本处理工具
- 中文分词（jieba）
- 文本清洗与归一化
- 文本截断与摘要截取
- 相似度计算
"""
from __future__ import annotations

import re
import math
from typing import List, Optional

from config.constants import DEFAULT_STOPWORDS
from utils.logger import get_logger

logger = get_logger(__name__)


# ==================== 文本清洗 ====================


def clean_text(text: str) -> str:
    """
    基础文本清洗：
    - 去除多余空白
    - 统一换行符
    - 去除不可见控制字符
    """
    if not text:
        return ""
    # 去除控制字符（保留换行、制表）
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # 统一换行
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 去除行首尾空格
    lines = [line.strip() for line in text.split("\n")]
    # 合并过多空行（最多保留 1 个空行）
    cleaned = []
    prev_empty = False
    for line in lines:
        is_empty = (line == "")
        if is_empty and prev_empty:
            continue
        cleaned.append(line)
        prev_empty = is_empty
    return "\n".join(cleaned).strip()


def remove_extra_whitespace(text: str) -> str:
    """去除多余空白字符（空格、制表、换行合并为单个空格）"""
    return re.sub(r"\s+", " ", text).strip()


def normalize_chinese_punctuation(text: str) -> str:
    """中文标点归一化（全角转半角的常见符号）"""
    mapping = {
        "，": ",", "。": ".", "！": "!", "？": "?",
        "：": ":", "；": ";", "“": '"', "”": '"',
        "‘": "'", "’": "'", "（": "(", "）": ")",
        "【": "[", "】": "]", "《": "<", "》": ">",
    }
    for c, e in mapping.items():
        text = text.replace(c, e)
    return text


# ==================== 中文分词 ====================


def jieba_segment(text: str, use_stopwords: bool = True) -> List[str]:
    """
    使用 jieba 进行中文分词。

    Args:
        text: 待分词文本
        use_stopwords: 是否去除停用词

    Returns:
        分词结果列表
    """
    try:
        import jieba
    except ImportError as e:
        raise ImportError("jieba 未安装，请执行 pip install jieba") from e

    text = clean_text(text)
    if not text:
        return []

    words = jieba.lcut(text)
    # 过滤
    words = [w.strip() for w in words if w.strip()]
    if use_stopwords:
        words = [w for w in words if w not in DEFAULT_STOPWORDS and len(w) > 1]
    return words


def tokenize_for_bm25(text: str) -> str:
    """
    为 BM25 索引生成分词后的字符串（空格分隔，便于 BM25 处理）。
    """
    words = jieba_segment(text, use_stopwords=False)
    return " ".join(words)


# ==================== 文本截断 ====================


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """
    按字符数截断文本。

    Args:
        text: 原文本
        max_length: 最大长度
        suffix: 截断后缀

    Returns:
        截断后的文本
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def truncate_by_tokens(text: str, max_tokens: int, token_estimator=None) -> str:
    """
    按 token 数截断文本。
    若未传入 token_estimator，则按 1 个中文 = 1.5 token 估算。
    """
    if token_estimator is None:
        # 粗略估计：中文约 1.5 token/字，英文约 0.75 token/词
        estimated = int(len(text) * 1.2)
        if estimated <= max_tokens:
            return text
        # 反推大概字符数
        chars = int(max_tokens / 1.2)
        return truncate_text(text, chars)

    # TODO: 支持 tiktoken 精确截断
    return text


# ==================== 相似度计算 ====================


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    if len(vec1) != len(vec2):
        raise ValueError("向量维度不一致")
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


# ==================== 其他工具 ====================


def extract_keywords(text: str, top_k: int = 10) -> List[str]:
    """
    简单关键词提取（基于词频）。
    如需更高质量，可升级为 jieba.analyse 或 TF-IDF。
    """
    words = jieba_segment(text, use_stopwords=True)
    if not words:
        return []
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:top_k]]


def count_tokens_estimate(text: str) -> int:
    """估算 token 数（粗略）"""
    if not text:
        return 0
    chinese_chars = len(re.findall(r"[一-鿿]", text))
    other_chars = len(text) - chinese_chars
    # 中文: 1字 ≈ 1.5 tokens, 英文/数字: 4字符 ≈ 1 token
    return int(chinese_chars * 1.5 + other_chars * 0.25)
