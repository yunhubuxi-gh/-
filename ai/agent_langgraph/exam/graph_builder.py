"""
试卷双 Agent 状态图构建（LangGraph）

构建「命题 → 逐题校验 → 不合格重生成」闭环：

    START → generator（命题）→ validator（校验评审）
                        │
                        └─(存在不合格 & 迭代未达上限)──> generator（仅重生成不合格题）
                        └─(全部合格 或 迭代达上限)────> END

命题 Agent 与校验评审 Agent 是两个独立节点，串联执行，绝不合并成单轮 LLM 调用。
迭代次数由 max_iterate 硬上限控制，防止死循环。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ai.agent_langgraph.exam.state import ExamState
from ai.agent_langgraph.exam.generator_node import make_generator_node
from ai.agent_langgraph.exam.validator_node import make_validator_node
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ExamDependencies:
    """试卷双 Agent 执行依赖（注入节点）"""
    llm_client: Optional[Any] = None
    rag_pipeline: Optional[Any] = None
    max_iterate: int = 3
    llm_timeout: float = 120.0
    llm_max_tokens: int = 4096
    rag_top_k: int = 6
    temperature: float = 0.0


def build_exam_graph(deps: ExamDependencies):
    """构建并编译试卷双 Agent 状态图"""
    try:
        from langgraph.graph import StateGraph, START, END
    except ImportError as e:
        raise ImportError("langgraph 未安装，请执行 pip install langgraph") from e

    generator = make_generator_node(
        llm_client=deps.llm_client,
        rag_pipeline=deps.rag_pipeline,
        max_tokens=deps.llm_max_tokens,
        timeout=deps.llm_timeout,
        rag_top_k=deps.rag_top_k,
        temperature=deps.temperature,
    )
    validator = make_validator_node(
        llm_client=deps.llm_client,
        rag_pipeline=deps.rag_pipeline,
        max_tokens=deps.llm_max_tokens,
        timeout=deps.llm_timeout,
        rag_top_k=deps.rag_top_k,
        temperature=deps.temperature,
    )

    def route_after_validator(state: dict):
        rejected = state.get("rejected_questions") or []
        iterate = int(state.get("iterate_count", 0))
        if rejected and iterate < int(state.get("max_iterate", deps.max_iterate)):
            return "generator"
        return END

    graph = StateGraph(ExamState)
    graph.add_node("generator", generator)
    graph.add_node("validator", validator)

    graph.add_edge(START, "generator")
    graph.add_edge("generator", "validator")
    graph.add_conditional_edges(
        "validator",
        route_after_validator,
        {"generator": "generator", END: END},
    )

    compiled = graph.compile()
    logger.info("试卷双 Agent 状态图构建完成")
    return compiled
