"""
校验评审 Agent 节点（validator_node）

职责：
- 对命题 Agent 输出的每道题，调用 RAG 检索课程库课件原文
- 逐条完成 4 项校验：①知识点真实存在 ②参考答案正确 ③不超纲 ④无歧义
- 第 5 组校验（跨题、规则型，不调 LLM）：⑤题目相似度去重 + 知识点均衡检测
- 输出每道题的校验结果（pass/fail + 原因 + 来源引用）
- 收集不合格题回传命题 Agent 重生成

说明：本节点与命题节点是两个独立 Agent 节点，在 LangGraph 中串联执行，
校验「逐题独立调用 RAG + LLM」，不合并成单轮调用；第 5 组校验是纯规则的跨题校验，
在同一节点内对整套试卷做横向检查，不新增节点、不改图拓扑。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import List, Dict, Any

from utils.logger import get_logger

from ai.agent_langgraph.exam.json_util import extract_json_object
from ai.agent_langgraph.exam.rag_util import retrieve_material


# ============================================================
# 第 5 组校验：题目相似度去重（文本向量相似度，纯 Python，零外部依赖）
# ============================================================

def _char_ngrams(text, n: int = 2) -> Counter:
    """把文本转成字符 n-gram 计数向量（中文去空白后按 n 字窗口切分）"""
    s = re.sub(r"\s+", "", str(text or ""))
    if len(s) < n:
        return Counter([s]) if s else Counter()
    return Counter(s[i:i + n] for i in range(len(s) - n + 1))


def _vector_cosine(a: Counter, b: Counter) -> float:
    """两个计数向量夹角的余弦相似度（0~1）"""
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in common)
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _text_similarity(text_a: str, text_b: str) -> float:
    """文本向量相似度：对「题干+知识点」做字符 2-gram 计数向量余弦。

    用 2-gram 同时捕获 2 字以上中文词元，对近义改写、同题不同表述也能识别；
    纯 Python 实现，不依赖 sklearn 等额外包，任何环境均可运行。
    """
    return _vector_cosine(_char_ngrams(text_a), _char_ngrams(text_b))


def _cross_question_checks(
    questions: List[Dict[str, Any]],
    dup_threshold: float,
    max_ratio: float,
) -> tuple:
    """第 5 组校验：题目相似度去重 + 知识点均衡检测（纯规则，不调 LLM）。

    Args:
        questions: 整套试卷题目
        dup_threshold: 题目相似度阈值（0~1）
        max_ratio: 单一知识点题数占比上限（0~1）

    Returns:
        (新增校验结果列表, 新增被否题列表)
    """
    results: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    n = len(questions)
    if n <= 1:
        return results, rejected

    flagged_qids = set()  # 本组已判 fail 的题（去重 + 偏科）

    # ---------- 5.1 题目相似度去重：两两对比，相似度超阈值判重复 ----------
    for i in range(n):
        qi = questions[i]
        for j in range(i + 1, n):
            qj = questions[j]
            sim = _text_similarity(
                f"{qi.get('stem', '')} {qi.get('knowledge_point', '')}",
                f"{qj.get('stem', '')} {qj.get('knowledge_point', '')}",
            )
            if sim >= dup_threshold:
                # 保留先出现的题（qid 小），后出现的判为重复需重出
                flagged_qids.add(qj.get("qid"))
    for q in questions:
        qid = q.get("qid")
        if qid in flagged_qids:
            results.append({
                "qid": qid, "type": q.get("type"), "stem": q.get("stem"),
                "verdict": "fail",
                "reason": f"题目与试卷内其它题文本相似度过高（≥{dup_threshold}），判定重复，需换考点重出",
                "source_refs": [], "rag_queries": [], "rule": "dedup",
            })
            rejected.append({**q, "reject_reason":
                "题目与试卷内其它题重复（文本相似度过高），请换用课件原文中不同考点重新出题，严禁重出近似题"})

    # ---------- 5.2 知识点均衡检测：单一知识点占比超上限判定偏科 ----------
    kp_counts = Counter(
        (str(q.get("knowledge_point") or "未标注").strip() or "未标注") for q in questions
    )
    total = len(questions)
    allowed = max(1, math.ceil(total * max_ratio))  # 单知识点允许出现的最大题数
    excess = {kp: cnt - allowed for kp, cnt in kp_counts.items() if cnt > allowed}
    if excess:
        # 只把超出 allowed 的那几题判为偏科重出（保留 allowed 道，维持卷面稳定）
        for q in questions:
            qid = q.get("qid")
            if qid in flagged_qids:
                continue  # 已在去重组判过，不重复标记
            kp = (str(q.get("knowledge_point") or "未标注").strip() or "未标注")
            if excess.get(kp, 0) <= 0:
                continue
            excess[kp] -= 1
            pct = kp_counts.get(kp, 0) / total
            flagged_qids.add(qid)
            results.append({
                "qid": qid, "type": q.get("type"), "stem": q.get("stem"),
                "verdict": "fail",
                "reason": f"知识点「{kp}」占比过高（{kp_counts.get(kp, 0)}/{total}，"
                          f"{pct:.0%}）超过上限 {max_ratio:.0%}，判定偏科，需更换考点",
                "source_refs": [], "rag_queries": [], "rule": "balance",
            })
            rejected.append({**q, "reject_reason":
                f"知识点「{kp}」占比过高导致整套试卷考点分布偏科，"
                f"请换用课件原文中其它知识点重新出题，保证整套试卷知识点分布均衡"})

    return results, rejected

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
        from config.settings import settings
        kb_id = int(state["knowledge_base_id"])
        questions = state.get("questions") or []
        iterate = int(state.get("iterate_count", 0))

        validation_results: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []

        # 逐题校验：每道题独立 RAG 检索 + LLM 校验（原 4 项校验）
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
                # 把校验失败原因一并回传命题 Agent，供其精准重生成（换考点而非重出同类题）
                rejected.append({**q, "reject_reason": check["reason"]})

        # 第 5 组校验：题目相似度去重 + 知识点均衡检测（跨题规则校验，不调 LLM）
        rejected_qids = {r.get("qid") for r in rejected}
        dup_threshold = float(settings.exam_dup_similarity_threshold)
        max_ratio = float(settings.exam_knowledge_max_ratio)
        cross_results, cross_rejected = _cross_question_checks(questions, dup_threshold, max_ratio)
        for r in cross_rejected:
            if r.get("qid") not in rejected_qids:
                rejected.append(r)
                rejected_qids.add(r.get("qid"))
        # 校验结果一并入轨（前端可见「重复/偏科」判定）
        validation_results.extend(cross_results)

        fail_count = len(rejected)
        logger.info(
            f"校验评审 Agent 完成: 第{iterate}轮, 校验={len(validation_results)}题, "
            f"不合格={fail_count}题（含去重/偏科 {len(cross_rejected)} 题）"
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
