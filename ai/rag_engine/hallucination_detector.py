"""
幻觉抑制模块

目标：回答必须依赖检索上下文，知识库无信息时明确告知，禁止编造。

实现思路（启发式 + 可扩展 LLM 校验）：
1. 上下文充分性检测：检索结果为空或相关性过低 → 判定「知识库无相关信息」
2. 无答案识别：检测回答中的「不知道 / 无法回答 / 未找到」等表述
3. 支撑度校验：提取回答关键词，计算与上下文的覆盖度；覆盖度过低 → 标记「可能存在编造」
4. 输出统一结构 HallucinationCheck，供上层决定是否拦截 / 提示

可配置开关：settings.hallucination_check_enabled
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from config.settings import settings
from utils.text_utils import extract_keywords
from utils.logger import get_logger

logger = get_logger(__name__)

# 无答案 / 拒绝回答 的典型表述
_NO_ANSWER_PATTERNS = [
    "不知道", "无法回答", "没有找到", "未找到", "未提供", "未提及",
    "没有相关信息", "无法提供", "无可奉告", "不清楚", "没有相关",
    "未检索到", "知识库中不存在", "暂无", "no information", "not found",
]

# 检索上下文相关性阈值（低于此值视为无有效上下文）
_MIN_CONTEXT_SCORE = 0.0


@dataclass
class HallucinationCheck:
    """幻觉抑制检测结果"""
    has_context: bool = False          # 是否存在有效检索上下文
    no_answer: bool = False            # 回答是否为「无答案」表述
    grounded: bool = True              # 回答是否被上下文支撑
    confidence: float = 0.0            # 支撑置信度 [0, 1]
    warnings: List[str] = field(default_factory=list)
    suggestion: str = ""               # 给上层的处理建议

    def should_suppress(self) -> bool:
        """是否需要抑制（拦截/替换）该回答"""
        if self.no_answer:
            return False  # 明确告知「不知道」是正确行为，不抑制
        if not self.has_context:
            return True   # 无上下文却给出实质回答 → 编造
        return not self.grounded


class HallucinationDetector:
    """幻觉抑制检测器"""

    def __init__(self, enabled: bool | None = None):
        self.enabled = enabled if enabled is not None else settings.hallucination_check_enabled

    def check(
        self,
        answer: str,
        contexts: List[str],
        context_scores: Optional[List[float]] = None,
    ) -> HallucinationCheck:
        """
        执行幻觉抑制检测。

        Args:
            answer: 模型生成的回答
            contexts: 检索到的上下文片段文本列表
            context_scores: 各上下文的相关性分数（可选）

        Returns:
            HallucinationCheck 检测结果
        """
        result = HallucinationCheck()

        if not self.enabled:
            result.grounded = True
            return result

        # 1. 上下文充分性
        valid = [c for c in contexts if c and c.strip()]
        result.has_context = len(valid) > 0

        # 2. 无答案识别（基于回答文本本身）
        result.no_answer = self._is_no_answer(answer)

        # 3. 无上下文场景
        if not result.has_context:
            if result.no_answer:
                # 明确告知「不知道」是正确行为
                result.grounded = True
                result.confidence = 1.0
                result.suggestion = "回答已明确表示无相关信息，符合幻觉抑制要求"
            else:
                result.grounded = False
                result.warnings.append("检索上下文为空")
                result.suggestion = "知识库中未找到相关信息，应明确告知用户，禁止编造"
            return result

        # 4. 有上下文但回答为「无答案」表述
        if result.no_answer:
            result.grounded = True
            result.confidence = 1.0
            result.suggestion = "回答已明确表示无相关信息，符合幻觉抑制要求"
            return result

        # 5. 支撑度校验（关键词覆盖度）
        result.confidence = self._grounding_confidence(answer, valid)
        result.grounded = result.confidence >= 0.3  # 覆盖度阈值
        if not result.grounded:
            result.warnings.append("回答关键信息在检索上下文中覆盖不足，可能存在编造")
            result.suggestion = "建议重写回答，仅基于检索上下文作答，并补充引用标注"

        return result

    # ---------- 内部工具 ----------

    @staticmethod
    def _is_no_answer(answer: str) -> bool:
        low = (answer or "").lower()
        return any(p in low for p in _NO_ANSWER_PATTERNS)

    @staticmethod
    def _grounding_confidence(answer: str, contexts: List[str]) -> float:
        """基于关键词覆盖度估算回答被上下文支撑的程度"""
        if not answer.strip():
            return 0.0
        keywords = extract_keywords(answer, top_k=15)
        if not keywords:
            return 0.0

        joined_context = " ".join(contexts)
        covered = 0
        for kw in keywords:
            if kw in joined_context:
                covered += 1
        return covered / len(keywords)


# 模块级便捷函数
_detector: Optional[HallucinationDetector] = None


def get_hallucination_detector() -> HallucinationDetector:
    global _detector
    if _detector is None:
        _detector = HallucinationDetector()
    return _detector


def reset_hallucination_detector() -> None:
    global _detector
    _detector = None
