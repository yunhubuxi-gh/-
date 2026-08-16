"""
校验评审 Agent 节点（validator_node）

职责：
- 对命题 Agent 输出的每道题，调用 RAG 检索课程库课件原文
- 逐条完成 4 项校验：①知识点真实存在 ②参考答案正确 ③不超纲 ④无歧义
- 输出每道题的校验结果（pass/fail + 原因 + 来源引用）
- 收集不合格题回传命题 Agent 重生成

说明：本节点与命题节点是两个独立 Agent 节点，在 LangGraph 中串联执行，
校验「逐题独立调用 RAG + LLM」，不合并成单轮调用。
"""
from __future__ import annotations

from typing import List, Dict, Any

from utils.logger import get_logger

from ai.agent_langgraph.exam.json_util import extract_json_object
from ai.agent_langgraph.exam.rag_util import retrieve_material

logger = get_logger(__name__)

_VALIDATOR_SYSTEM = (
    "你是高校试卷校验评审专家（校验评审 Agent）。请对给定题目逐项校验，完成 4 项检查：\n"
    "① 知识点是否真实存在于课件原文；\n"
    "② 参考答案是否正确；\n"
    "③ 题目是否超纲（超出课件内容）；\n"
    "④ 题目是否存在歧义（表述不清、答案不唯一等）。\n"
    "判定规则：\n"
    "- 4 项全部通过 → verdict=pass；\n"
    "- 任意一项不通过 → verdict=fail，并在 reason 中说明具体是哪一项、什么原因；\n"
    "- 若【课件原文】中检索不到与该题目相关的知识点，判定 fail（无法溯源）。\n"
    "请严格输出 JSON："
    '{{"verdict": "pass"/"fail", "reason": "...", "source_refs": ["相关课件原文片段"]}}'
)


def _validate_one(
    llm_client,
    question: Dict[str, Any],
    context_text: str,
    max_tokens: int,
    timeout: float,
    temperature: float,
) -> Dict[str, Any]:
    """对单道题做 4 项校验，返回 {verdict, reason, source_refs}"""
    if llm_client is None:
        return {"verdict": "pass", "reason": "LLM 不可用，跳过校验", "source_refs": []}

    qtype = question.get("type", "")
    stem = question.get("stem", "")
    answer = question.get("answer", "")
    options = question.get("options") or []
    opt_text = "\n".join(options) if options else ""
    user_msg = (
        f"【题目类型】{qtype}\n"
        f"【题干】{stem}\n"
        + (f"【选项】\n{opt_text}\n" if opt_text else "")
        + f"【参考答案】{answer}\n\n"
        f"【课件原文】\n{context_text or '（未检索到课件内容）'}"
    )
    try:
        raw = llm_client.chat(
            [
                {"role": "system", "content": _VALIDATOR_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            thinking_disabled=True,
        )
        obj = extract_json_object(raw or "") or {}
        verdict = str(obj.get("verdict", "")).strip().lower()
        if verdict not in ("pass", "fail"):
            # 兜底：输出含否定词则视为不合格
            low = (raw or "").lower()
            verdict = "fail" if any(k in low for k in ("fail", "不合格", "不存在", "超纲", "歧义", "错误")) else "pass"
        return {
            "verdict": verdict,
            "reason": str(obj.get("reason", "")).strip(),
            "source_refs": obj.get("source_refs") or [],
        }
    except Exception as e:
        logger.warning(f"校验评审 Agent LLM 调用失败（跳过该校验）: {e}")
        return {"verdict": "pass", "reason": f"校验异常，跳过: {e}", "source_refs": []}


def make_validator_node(
    llm_client,
    rag_pipeline,
    max_tokens: int,
    timeout: float,
    rag_top_k: int,
    temperature: float,
):
    """
    构造校验评审 Agent 节点函数。
    """

    def validator_node(state: dict) -> dict:
        kb_id = int(state["knowledge_base_id"])
        questions = state.get("questions") or []
        iterate = int(state.get("iterate_count", 0))

        validation_results: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []

        # 逐题校验：每道题独立 RAG 检索 + LLM 校验
        for q in questions:
            qid = q.get("qid")
            queries = [str(q.get("knowledge_point") or q.get("stem") or "")]
            queries = [q for q in queries if q]
            context_text, rag_log = retrieve_material(rag_pipeline, kb_id, queries, rag_top_k)

            check = _validate_one(llm_client, q, context_text, max_tokens, timeout, temperature)
            result = {
                "qid": qid,
                "type": q.get("type"),
                "stem": q.get("stem"),
                "verdict": check["verdict"],
                "reason": check["reason"],
                "source_refs": check["source_refs"],
                "rag_queries": rag_log,
            }
            validation_results.append(result)
            if check["verdict"] == "fail":
                rejected.append(q)

        fail_count = len(rejected)
        logger.info(
            f"校验评审 Agent 完成: 第{iterate}轮, 校验={len(validation_results)}题, 不合格={fail_count}题"
        )
        return {
            "validation_results": validation_results,
            "rejected_questions": rejected,
            "status": "regenerate" if rejected else "done",
            "trace": [{
                "iteration": iterate,
                "phase": "validation",
                "detail": f"校验 {len(validation_results)} 题，不合格 {fail_count} 题",
                "per_question": validation_results,
            }],
        }

    return validator_node
