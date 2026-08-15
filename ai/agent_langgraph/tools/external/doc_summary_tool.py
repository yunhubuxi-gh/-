"""
【外部业务工具】文档摘要工具

对给定文本生成摘要。优先使用 LLM 生成摘要，LLM 不可用时降级为
抽取式摘要（关键词 + 前若干句），保证工具始终可用。
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

from ai.agent_langgraph.tools.base_tool import BaseTool, ToolCategory
from utils.text_utils import extract_keywords
from utils.logger import get_logger

logger = get_logger(__name__)


class DocSummaryInput(BaseModel):
    """文档摘要工具输入"""
    content: str = Field(..., description="待摘要的文本内容")
    max_length: int = Field(200, description="摘要最大长度（字符）", ge=20, le=2000)


class DocSummaryOutput(BaseModel):
    """文档摘要工具输出"""
    summary: str = Field(description="生成的摘要")


class DocSummaryTool(BaseTool):
    """文档摘要工具（外部业务工具）"""

    name = "doc_summary"
    display_name = "文档摘要"
    category = ToolCategory.EXTERNAL_BIZ
    description = (
        "对一段文本生成简洁摘要。当需要提炼文档要点、压缩长文本、"
        "概括报告内容时使用。输入待摘要文本，返回摘要。"
    )

    args_schema = DocSummaryInput
    result_schema = DocSummaryOutput

    def __init__(self, llm_client=None):
        self._llm_client = llm_client

    def _get_llm(self):
        if self._llm_client is None:
            from utils.llm_client import get_llm_client
            self._llm_client = get_llm_client()
        return self._llm_client

    def _execute(self, input_data: DocSummaryInput) -> DocSummaryOutput:
        content = input_data.content.strip()
        if not content:
            return DocSummaryOutput(summary="")

        # 优先 LLM 摘要
        try:
            llm = self._get_llm()
            summary = llm.chat([
                {"role": "system", "content": "你是文档摘要助手，请用简洁的中文总结要点。"},
                {"role": "user", "content": f"请对以下内容生成不超过{input_data.max_length}字的摘要：\n{content}"},
            ])
            summary = summary.strip()[:input_data.max_length]
            if summary:
                return DocSummaryOutput(summary=summary)
        except Exception as e:
            logger.warning(f"LLM 摘要失败，降级为抽取式摘要: {e}")

        # 降级：抽取式摘要
        summary = self._extractive_summary(content, input_data.max_length)
        return DocSummaryOutput(summary=summary)

    @staticmethod
    def _extractive_summary(content: str, max_length: int) -> str:
        """抽取式摘要：关键词 + 前若干句"""
        try:
            keywords = extract_keywords(content, top_k=5)
        except Exception:
            keywords = []
        sentences = [s.strip() for s in content.replace("\n", " ").split("。") if s.strip()]
        picked = sentences[:3]
        summary = "。".join(picked) + "。"
        if keywords:
            summary = f"[关键词：{'、'.join(keywords)}] " + summary
        return summary[:max_length]
