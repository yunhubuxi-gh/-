"""
批改模块（grader）—— 精细化溯源批改

职责：
- 主观题（简答题）：基于课程库课件原文做「四维度分项溯源批改」。
  四个维度（权重可在 .env 配置）：
    ① 知识点匹配度  ② 答题步骤完整性  ③ 结论答案正确性  ④ 语言表述规范性
  每个维度独立打分 + 独立点评 + 独立课件原文来源引用（防幻觉）。
- 客观题（选择/填空）：规则判分在 services 层完成；本模块仅对「答错」的客观题补充
  「错误解析」——说明为什么错、本题考察知识点、课件溯源片段。
- 客观题判分本身走规则，不调 LLM（省成本）；仅答错时才调 LLM 做错误解析。

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

# 主观题四维度定义（key 供程序识别，label 展示用）
_SUBJECTIVE_DIMS = [
    ("knowledge", "知识点匹配度", "exam_grade_weight_knowledge"),
    ("steps", "答题步骤完整性", "exam_grade_weight_steps"),
    ("conclusion", "结论答案正确性", "exam_grade_weight_conclusion"),
    ("language", "语言表述规范性", "exam_grade_weight_language"),
]
# LLM 输出中维度 key 的可能写法 → 标准化 key
_DIM_KEY_ALIAS = {
    "knowledge": "knowledge", "知识点": "knowledge", "知识点匹配度": "knowledge",
    "steps": "steps", "步骤": "steps", "步骤完整性": "steps", "答题步骤完整性": "steps",
    "conclusion": "conclusion", "结论": "conclusion", "结论正确性": "conclusion",
    "结论答案正确性": "conclusion", "结论答案正确": "conclusion",
    "language": "language", "语言": "language", "表述": "language",
    "语言表述规范性": "language", "语言表述": "language", "规范性": "language",
}

# 主观题批改系统提示（四维度分项）
_GRADER_SYSTEM = (
    "你是高校课程助教，负责基于课件原文对学生的简答题进行严谨的「四维度分项」批改。\n"
    "四个评分维度与权重如下（每个维度独立打分、独立点评）：\n"
    "① 知识点匹配度：作答是否覆盖题目考察的核心知识点；\n"
    "② 答题步骤完整性：论述/推导步骤是否完整、有逻辑层次；\n"
    "③ 结论答案正确性：最终结论/答案是否正确；\n"
    "④ 语言表述规范性：表述是否清晰、术语是否规范。\n"
    "要求：\n"
    "1. 严格依据【课件原文】评判，不得用课外知识打分；\n"
    "2. 参照【参考答案】判断要点是否覆盖；\n"
    "3. dimensions 数组里每个维度给出 0~该维度满分的整数 score、comment 点评、"
    "source_refs（从【课件原文】逐字摘录能支撑该维度评判的句子，禁止改写/编造）；\n"
    "4. strengths 列出学生答对/答好的总体要点；missing 列出遗漏或答错的知识点；\n"
    "5. 顶层不再要求 score（系统会自动求和各维度得分）。\n"
    "请严格输出 JSON："
    '{"dimensions": [{"key": "knowledge", "score": 0, "comment": "...", "source_refs": ["..."]},'
    '{"key": "steps", "score": 0, "comment": "...", "source_refs": ["..."]},'
    '{"key": "conclusion", "score": 0, "comment": "...", "source_refs": ["..."]},'
    '{"key": "language", "score": 0, "comment": "...", "source_refs": ["..."]}],'
    '"strengths": ["..."], "missing": ["..."]}'
)

# 客观题错误解析系统提示
_OBJECTIVE_EXPLAIN_SYSTEM = (
    "你是高校课程助教，负责给学生的客观题（单选题/填空题）做「错误解析」。\n"
    "要求：\n"
    "1. 结合【课件原文素材】解释学生作答为什么不对（单选：所选错误选项错在哪里；"
    "填空：填写的答案缺了什么/错在哪里）；\n"
    "2. analysis 用中文简洁说明，必须指向课件原文中的依据，不得凭空发挥；\n"
    "3. source_refs 必须从【课件原文素材】中逐字摘录能支撑解析的句子（禁止改写/编造）。\n"
    "请严格输出 JSON："
    '{"analysis": "...", "source_refs": ["课件原文逐字摘录"]}'
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


def _subjective_weights() -> Dict[str, float]:
    """读取 .env 配置的四维度权重并归一化（兼容 30/30/20/20 与 0.3/0.3/0.2/0.2）"""
    weights = {
        "knowledge": float(settings.exam_grade_weight_knowledge),
        "steps": float(settings.exam_grade_weight_steps),
        "conclusion": float(settings.exam_grade_weight_conclusion),
        "language": float(settings.exam_grade_weight_language),
    }
    total = sum(weights.values())
    if total <= 0:
        return {k: 0.25 for k in weights}
    return {k: v / total for k, v in weights.items()}


def _dimension_maxes(max_score: int, weights: Dict[str, float]) -> List[Dict[str, Any]]:
    """按权重把满分拆到四个维度（余数按小数部分从大到小分配，保证各维满分之和=满分）"""
    exact = [max_score * weights[key] for key, _, _ in _SUBJECTIVE_DIMS]
    floors = [int(e) for e in exact]
    leftover = max_score - sum(floors)
    order = sorted(range(len(_SUBJECTIVE_DIMS)), key=lambda i: exact[i] - floors[i], reverse=True)
    for i in order[: max(0, leftover)]:
        floors[i] += 1
    result = []
    for i, (key, label, _cfg) in enumerate(_SUBJECTIVE_DIMS):
        result.append({"key": key, "label": label, "max_score": floors[i]})
    return result


class GradeManager:
    """批改管理器（RAG 溯源 + LLM 判分）：主观题分项批改 + 客观题错误解析"""

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

    # ============================================================
    # 主观题：四维度分项溯源批改
    # ============================================================

    def grade_subjective(
        self,
        kb_id: int,
        question: Dict[str, Any],
        student_answer: str,
    ) -> Dict[str, Any]:
        """
        批改一道简答题（四维度分项打分）。

        Returns:
            {qid, score, max_score, dimensions[{key,label,weight,score,max_score,comment,source_refs}],
             strengths, missing, source_refs, error}
        """
        qid = question.get("qid")
        max_score = int(question.get("score") or 0)
        stem = str(question.get("stem") or "").strip()
        ref_answer = str(question.get("answer") or "").strip()
        student_answer = str(student_answer or "").strip()
        weights = _subjective_weights()
        dim_maxes = _dimension_maxes(max_score, weights)

        base = {
            "qid": qid,
            "score": 0,
            "max_score": max_score,
            "dimensions": [
                {"key": d["key"], "label": d["label"], "weight": round(weights[d["key"]], 2),
                 "max_score": d["max_score"], "score": 0, "comment": "", "source_refs": []}
                for d in dim_maxes
            ],
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

        # 2. LLM 分项判分（推理模型偶发返回空 content，重试一次 + 明确报错，避免静默判 0 分）
        llm_client = self._get_llm()
        if llm_client is None:
            base["error"] = "LLM 不可用"
            return base
        weight_desc = "；".join(
            f"{d['label']}（{round(weights[d['key']] * 100)}%，满分 {d['max_score']} 分）"
            for d in dim_maxes
        )
        user_msg = (
            f"【题目】{stem}\n"
            f"【参考答案】{ref_answer}\n"
            f"【满分】{max_score} 分，各维度满分分配：{weight_desc}\n"
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
                logger.warning(f"主观题分项批改 LLM 调用失败(第{attempt}次): qid={qid}, err={e}")
                continue
            obj = extract_json_object(raw or "") or {}
            if obj:
                break
            last_err = "LLM 返回内容为空或无法解析为 JSON"
            logger.warning(f"主观题分项批改 LLM 返回无法解析(第{attempt}次): qid={qid}, raw={str(raw)[:200]!r}")
        if not obj:
            base["error"] = last_err or "LLM 批改失败"
            return base

        # 3. 解析各维度得分（夹在 0~该维度满分），溯源锚定
        dim_out_map = {}
        for d in obj.get("dimensions") or []:
            if not isinstance(d, dict):
                continue
            key = str(d.get("key") or "").strip().lower()
            key = _DIM_KEY_ALIAS.get(key, key)
            dim_out_map[key] = d

        total_score = 0
        merged_refs: List[str] = []
        for dim in base["dimensions"]:
            out = dim_out_map.get(dim["key"])
            if not out:
                continue
            try:
                sc = int(out.get("score", 0))
            except (TypeError, ValueError):
                sc = 0
            dim["score"] = max(0, min(dim["max_score"], sc))
            dim["comment"] = str(out.get("comment") or "").strip()
            raw_refs = _normalize_text_list(out.get("source_refs"))
            anchored = [r for r in raw_refs if r and r in context_text]
            dim["source_refs"] = anchored
            merged_refs.extend(anchored)
            total_score += dim["score"]

        # 4. 总体优点/缺失 + 兜底溯源（各维度都无锚定引用时，回退 top 检索片段首句）
        base["strengths"] = _normalize_text_list(obj.get("strengths"))
        base["missing"] = _normalize_text_list(obj.get("missing"))
        if not merged_refs and contents:
            merged_refs = [c[:120] for c in contents[:2] if c]
        base["source_refs"] = merged_refs[:6]
        base["score"] = max(0, min(max_score, total_score))

        return base

    # ============================================================
    # 客观题：错误解析（仅答错时调用）
    # ============================================================

    def grade_objective_detail(
        self,
        kb_id: int,
        question: Dict[str, Any],
        student_answer: str,
        score: int,
    ) -> Dict[str, Any]:
        """
        对答错的客观题（单选/填空）生成错误解析：为什么错 + 考察知识点 + 课件溯源片段。

        Returns:
            {analysis, knowledge_point, source_refs, error}
        """
        qtype = str(question.get("type") or "")
        stem = str(question.get("stem") or "").strip()
        ref_answer = str(question.get("answer") or "").strip()
        kp = str(question.get("knowledge_point") or "").strip()
        stu = str(student_answer or "").strip()
        options = question.get("options") or []

        base = {
            "analysis": "",
            "knowledge_point": kp,
            "source_refs": [],
            "error": None,
        }
        if not stu or not ref_answer:
            base["error"] = "缺少作答或参考答案，跳过错误解析"
            return base

        # 溯源素材：优先题目自带的 source_refs（命题时已逐字摘录），缺失则 RAG 检索知识点
        refs = [r for r in (question.get("source_refs") or []) if r]
        if not refs:
            _, contents = self._retrieve(kb_id, kp or stem, int(settings.exam_rag_top_k))
            refs = contents[:3]
        material = "\n".join(f"- {r}" for r in refs) if refs else "（未检索到课件素材）"

        llm_client = self._get_llm()
        if llm_client is None:
            base["error"] = "LLM 不可用"
            return base

        opt_text = "\n".join(options) if options else ""
        user_msg = (
            f"【题目类型】{'单选题' if qtype == 'choice' else '填空题'}\n"
            f"【题干】{stem}\n"
            + (f"【选项】\n{opt_text}\n" if opt_text else "")
            + f"【正确选项/参考答案】{ref_answer}\n"
            f"【学生作答】{stu}（该题得 {score} 分，作答错误）\n"
            f"【本题考察知识点】{kp or '未知'}\n\n"
            f"【课件原文素材】\n{material}"
        )
        obj: Dict[str, Any] = {}
        last_err: Optional[str] = None
        for attempt in (1, 2):
            try:
                raw = llm_client.chat(
                    [
                        {"role": "system", "content": _OBJECTIVE_EXPLAIN_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=float(settings.exam_temperature),
                    max_tokens=1024,
                    timeout=float(settings.exam_llm_timeout),
                )
            except Exception as e:
                last_err = str(e)
                logger.warning(f"客观题错误解析 LLM 调用失败(第{attempt}次): qid={question.get('qid')}, err={e}")
                continue
            obj = extract_json_object(raw or "") or {}
            if obj:
                break
            last_err = "LLM 返回内容为空或无法解析为 JSON"
        if not obj:
            base["error"] = last_err or "LLM 解析失败"
            return base

        base["analysis"] = str(obj.get("analysis") or "").strip()
        raw_refs = _normalize_text_list(obj.get("source_refs"))
        anchored = [r for r in raw_refs if r and r in material]
        if not anchored and refs:
            anchored = [r[:120] for r in refs[:2]]
        base["source_refs"] = anchored
        return base
