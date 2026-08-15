"""
主观题批改模块（grader）

职责：
- 对简答题（主观题）基于课程库课件原文做「溯源批改」：检索课件 → LLM 判分
- 输出 ① 得分 ② 优点 + 缺失知识点 ③ 每条评判的课件原文来源引用（防幻觉）
- 客观题（选择/填空）判分在 services 层用规则完成，不走本模块（不调 LLM）

硬性约束：
- 来源引用必须从课件原文逐字摘录，本模块做「溯源锚定」——只保留能匹配到课件原文的引用，
  LLM 编造的引用一律丢弃；若锚定后为空，回退到 top 检索片段，保证不出现无出处的引用。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config.settings import settings
from utils.logger import get_logger

from ai.agent_langgraph.exam.json_util import extract_json_object

logger = get_logger(__name__)

# 主观题批改系统提示
_GRADER_SYSTEM = (
    "你是高校课程助教，负责基于课件原文对学生的简答题进行严谨批改。\n"
    "要求：\n"
    "1. 严格依据【课件原文】评判学生答案，不得用课外知识打分；\n"
    "2. 参照【参考答案】判断作答是否覆盖要点；\n"
    "3. score 为 0~满分 的整数，按作答与参考答案的吻合度给分；\n"
    "4. strengths 列出学生答对/答好的要点（数组）；\n"
    "5. missing 列出学生遗漏或答错的知识点（数组）；\n"
    "6. source_refs 必须从【课件原文】中逐字摘录能支撑评判的句子（数组，禁止改写/编造）。\n"
    "请严格输出 JSON："
    '{{"score": 0, "strengths": ["..."], "missing": ["..."], "source_refs": ["课件原文逐字摘录"]}}'
)


def _normalize_text_list(value: Any) -> List[str]:
    """把 LLM 输出的字符串/列表规范化为非空字符串列表"""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


class GradeManager:
    """主观题批改管理器（RAG 溯源 + LLM 判分）"""

    def __init__(self, llm_client=None, rag_pipeline=None):
        # 可注入（测试用 Fake），缺省懒加载真实组件
        self.llm_client = llm_client
        self.rag_pipeline = rag_pipeline

    def _get_llm(self):
        if self.llm_client is None:
            from utils.llm_client import get_llm_client
            self.llm_client = get_llm_client()
        return self.llm_client

    def _get_rag_pipeline(self):
        if self.rag_pipeline is None:
            from ai.rag_engine.rag_pipeline import RagPipeline
            self.rag_pipeline = RagPipeline()
        return self.rag_pipeline

    def _retrieve(self, kb_id: int, query: str, top_k: int):
        """检索课件原文，返回 (格式化上下文, 原始片段列表)"""
        rag_pipeline = self._get_rag_pipeline()
        try:
            chunks = rag_pipeline.retrieve(query, [kb_id], top_k=top_k)
        except Exception as e:
            logger.warning(f"批改 RAG 检索失败: {e}")
            return "", []
        parts: List[str] = []
        contents: List[str] = []
        for c in chunks:
            doc = c.document_name or f"文档{c.document_id}"
            page = f"第{c.page_number}页" if c.page_number else ""
            parts.append(f"【{doc}{page}】\n{c.content}")
            contents.append(c.content)
        return "\n\n".join(parts), contents

    def grade_subjective(
        self,
        kb_id: int,
        question: Dict[str, Any],
        student_answer: str,
    ) -> Dict[str, Any]:
        """
        批改一道简答题。

        Returns:
            {qid, score, max_score, strengths, missing, source_refs, error}
        """
        qid = question.get("qid")
        max_score = int(question.get("score") or 0)
        stem = str(question.get("stem") or "").strip()
        ref_answer = str(question.get("answer") or "").strip()
        student_answer = str(student_answer or "").strip()

        base = {
            "qid": qid,
            "score": 0,
            "max_score": max_score,
            "strengths": [],
            "missing": [],
            "source_refs": [],
            "error": None,
        }

        if not student_answer:
            base["missing"] = ["未作答"]
            return base

        # 1. 检索课件原文（知识点 + 题干双路）
        query = question.get("knowledge_point") or stem or ""
        context_text, contents = self._retrieve(kb_id, query, int(settings.exam_rag_top_k))
        if not context_text:
            base["missing"] = ["未检索到课件素材，无法溯源批改"]
            base["error"] = "RAG 检索为空"
            return base

        # 2. LLM 判分（推理模型偶发返回空 content，重试一次 + 明确报错，避免静默判 0 分）
        llm_client = self._get_llm()
        if llm_client is None:
            base["error"] = "LLM 不可用"
            return base
        user_msg = (
            f"【题目】{stem}\n"
            f"【参考答案】{ref_answer}\n"
            f"【满分】{max_score}\n"
            f"【学生作答】{student_answer}\n\n"
            f"【课件原文】\n{context_text}"
        )
        obj: Dict[str, Any] = {}
        last_err: Optional[str] = None
        for attempt in (1, 2):
            try:
                raw = llm_client.chat(
                    [
                        {"role": "system", "content": _GRADER_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=float(settings.exam_temperature),
                    max_tokens=int(settings.exam_llm_max_tokens),
                    timeout=float(settings.exam_llm_timeout),
                )
            except Exception as e:
                last_err = str(e)
                logger.warning(f"主观题批改 LLM 调用失败(第{attempt}次): qid={qid}, err={e}")
                continue
            obj = extract_json_object(raw or "") or {}
            if obj:
                break
            last_err = "LLM 返回内容为空或无法解析为 JSON"
            logger.warning(f"主观题批改 LLM 返回无法解析(第{attempt}次): qid={qid}, raw={str(raw)[:200]!r}")
        if not obj:
            base["error"] = last_err or "LLM 批改失败"
            return base

        # 3. 得分（夹在 0~满分）
        try:
            score = int(obj.get("score", 0))
        except (TypeError, ValueError):
            score = 0
        base["score"] = max(0, min(max_score, score))
        base["strengths"] = _normalize_text_list(obj.get("strengths"))
        base["missing"] = _normalize_text_list(obj.get("missing"))

        # 4. 溯源锚定：仅保留能匹配到课件原文的引用，防幻觉
        raw_refs = _normalize_text_list(obj.get("source_refs"))
        anchored = [r for r in raw_refs if r and r in context_text]
        if not anchored and contents:
            # 回退：取 top 检索片段首句，保证有出处
            anchored = [c[:120] for c in contents[:2] if c]
        base["source_refs"] = anchored

        return base
