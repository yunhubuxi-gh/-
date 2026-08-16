"""
命题 Agent 节点（generator_node）

职责：
1. 主动多次调用 RAG 检索课程库课件原文（按题型/概述分别检索）
2. 基于检索到的课件原文，调用 LLM 生成结构化试卷（题目 + 参考答案 + 知识点 + 来源引用）
3. 迭代时，仅针对校验评审 Agent 判为不合格的题重新出题

硬性约束：
- 出题素材必须来自知识库，禁止凭空编造知识点（prompt 中反复强调）
- 失败/解析不出结果时降级，不中断整个工作流
"""
from __future__ import annotations

import json
from typing import List, Dict, Any, Callable, Optional

from config.constants import ExamQuestionType, DEFAULT_QUESTION_SCORE
from utils.logger import get_logger

from ai.agent_langgraph.exam.json_util import extract_questions
from ai.agent_langgraph.exam.rag_util import retrieve_material

logger = get_logger(__name__)

# 命题 Agent 系统提示
_GENERATOR_SYSTEM = (
    "你是高校课程试卷命题专家（命题 Agent）。你必须严格基于【课件原文素材】出题，"
    "严禁使用外部知识或凭空编造知识点。出题要求：\n"
    "1. 每道题的知识点都必须真实存在于课件原文中，不得超纲；\n"
    "2. 单选题：给出 4 个选项（A/B/C/D），只有一个正确答案；\n"
    "3. 填空题：题干中用 ___ 表示空位；\n"
    "4. 简答题：考察综合理解，答案需分点论述；\n"
    "5. 每道题必须给出参考答案、知识点名称、来源引用（source_refs 必须从课件原文素材中逐字摘录）。\n"
    "请严格输出 JSON，格式：\n"
    '{{"questions": ['
    '{{"type": "choice", "stem": "...", "options": ["A. ...", "B. ...", "C. ...", "D. ..."], '
    '"answer": "A", "knowledge_point": "...", "source_refs": ["..."]}},'
    '{{"type": "fill", "stem": "...", "answer": "...", "knowledge_point": "...", "source_refs": ["..."]}},'
    '{{"type": "short", "stem": "...", "answer": "...", "knowledge_point": "...", "source_refs": ["..."]}}'
    ']}}'
)


def _build_retrieval_queries(question_config: Dict[str, int]) -> List[str]:
    """根据题型配置构建多路检索查询（主动多次检索课件原文）"""
    queries: List[str] = []
    if question_config.get("choice", 0) > 0:
        queries.append("核心概念 定义 术语 分类 特点")
    if question_config.get("fill", 0) > 0:
        queries.append("关键名词 公式 结论 要点 规则")
    if question_config.get("short", 0) > 0:
        queries.append("原理 应用 论述 总结 对比 关系")
    if not queries:
        queries.append("课程重点 核心知识点 概述")
    return queries


def _normalize_questions(raw_questions: List[dict]) -> List[dict]:
    """规范化 LLM 输出的题目：过滤无效、补默认字段、按题型赋分值"""
    valid_types = {t.value for t in ExamQuestionType}
    result: List[dict] = []
    for raw in raw_questions:
        if not isinstance(raw, dict):
            continue
        qtype = str(raw.get("type", "")).strip().lower()
        if qtype not in valid_types:
            continue
        stem = str(raw.get("stem", "")).strip()
        if not stem:
            continue
        item = {
            "type": qtype,
            "stem": stem,
            "answer": str(raw.get("answer", "")).strip(),
            "knowledge_point": str(raw.get("knowledge_point", "")).strip(),
            "source_refs": raw.get("source_refs") or [],
        }
        if qtype == ExamQuestionType.CHOICE.value:
            options = raw.get("options") or []
            item["options"] = [str(o).strip() for o in options if str(o).strip()]
        # 统一按题型赋分值
        item["score"] = DEFAULT_QUESTION_SCORE.get(qtype, 5)
        result.append(item)
    return result


def make_generator_node(
    llm_client,
    rag_pipeline,
    max_tokens: int,
    timeout: float,
    rag_top_k: int,
    temperature: float,
):
    """
    构造命题 Agent 节点函数。

    Args:
        llm_client: LLM 客户端（chat(messages, ...) -> str）
        rag_pipeline: RagPipeline（retrieve(query, [kb_id], top_k)）
        max_tokens: LLM 最大输出 token
        timeout: LLM 超时（秒）
        rag_top_k: RAG 召回条数
        temperature: LLM 温度
    """

    def generator_node(state: dict) -> dict:
        kb_id = int(state["knowledge_base_id"])
        question_config = state.get("question_config") or {}
        difficulty = state.get("difficulty", "medium")
        rejected = state.get("rejected_questions") or []
        current_questions = state.get("questions") or []
        iterate = int(state.get("iterate_count", 0)) + 1

        # 1. 主动多次调用 RAG 检索课件原文
        queries = _build_retrieval_queries(question_config)
        if rejected:
            # 迭代重生成：额外检索不合格题涉及的知识点
            for r in rejected:
                queries.append(str(r.get("knowledge_point") or r.get("stem") or ""))
            queries = [q for q in queries if q]
        context_text, rag_log = retrieve_material(rag_pipeline, kb_id, queries, rag_top_k)

        # 2. 构建 LLM 提示
        if not rejected:
            # 首次：按题型配置出整套卷
            user_parts = [
                f"【题型配置】单选题 {question_config.get('choice', 0)} 道、"
                f"填空题 {question_config.get('fill', 0)} 道、"
                f"简答题 {question_config.get('short', 0)} 道",
                f"【难度】{difficulty}",
                f"【课件原文素材】\n{context_text or '（未检索到课件内容）'}",
            ]
            target_desc = "请按题型配置生成整套试卷"
        else:
            # 迭代：只重生成不合格题（保持题型与数量一致）
            rejected_desc = "\n".join(
                f"- 第{r['qid']}题（{r.get('type')}）：{r.get('stem')}" for r in rejected
            )
            user_parts = [
                f"【难度】{difficulty}",
                f"【课件原文素材】\n{context_text or '（未检索到课件内容）'}",
                f"【被判定不合格、需重生成的题目】\n{rejected_desc}",
                "请仅针对上述不合格题目重新出题，保持题型与数量不变，输出同样数量的题目",
            ]
            target_desc = "重新生成不合格题目"
        user_msg = "\n\n".join(user_parts)

        # 3. 调用 LLM 生成 + 解析
        new_questions: List[dict] = []
        gen_error: Optional[str] = None
        if llm_client is not None:
            try:
                raw = llm_client.chat(
                    [
                        {"role": "system", "content": _GENERATOR_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    thinking_disabled=True,
                )
                new_questions = _normalize_questions(extract_questions(raw or ""))
            except Exception as e:
                logger.warning(f"命题 Agent LLM 调用失败: {e}")
                gen_error = str(e)

        if not new_questions:
            logger.warning("命题 Agent 未产出有效题目")
            return {
                "status": "done",
                "error": gen_error or "命题 Agent 未产出有效题目",
                "trace": [{
                    "iteration": iterate,
                    "phase": "generation",
                    "detail": target_desc,
                    "rag_queries": rag_log,
                    "question_count": 0,
                    "error": gen_error,
                }],
            }

        # 4. 合并题目（迭代时替换不合格题，保持 qid 稳定）
        if rejected:
            by_qid = {q.get("qid"): q for q in current_questions}
            for i, old in enumerate(rejected):
                if i < len(new_questions):
                    new_questions[i]["qid"] = old.get("qid")
                    by_qid[old.get("qid")] = new_questions[i]
            merged = [by_qid[k] for k in sorted(by_qid.keys())]
        else:
            merged = new_questions

        # 重新统一编号 + 赋 qid
        for i, q in enumerate(merged):
            q["qid"] = i + 1

        logger.info(
            f"命题 Agent 完成: 第{iterate}轮, 题目数={len(merged)}, 检索={len(rag_log)}路"
        )
        return {
            "questions": merged,
            "rejected_questions": [],
            "iterate_count": iterate,
            "status": "validating",
            "error": None,
            "trace": [{
                "iteration": iterate,
                "phase": "generation",
                "detail": target_desc,
                "rag_queries": rag_log,
                "question_count": len(merged),
                "error": gen_error,
            }],
        }

    return generator_node
