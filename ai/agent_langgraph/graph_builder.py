"""
Agent 状态图构建（LangGraph）

构建「任务拆解 → 工具执行 → 结果判断 → 失败反思重试」闭环：

    START → planner → executor ──(成功)──> responder → END
                          │
                          └─(失败, 重试<上限)──> reflector → planner（重新规划）
                          └─(失败, 重试≥上限)──> responder → END

依赖通过 AgentDependencies 注入，节点工厂函数（nodes 模块）通过闭包绑定依赖。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Any, Optional, Callable

from ai.agent_langgraph.state import AgentState
from ai.agent_langgraph.nodes import (
    make_planner_node,
    make_executor_node,
    make_reflector_node,
    make_responder_node,
)
from config.constants import AgentTaskStatus
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AgentDependencies:
    """Agent 执行依赖（注入节点）"""
    llm_client: Optional[Any] = None
    tool_registry: Optional[Any] = None
    knowledge_base_ids: List[Any] = field(default_factory=list)
    max_retry: int = 3
    max_plan_steps: int = 5
    get_long_term_context: Optional[Callable] = None


def build_agent_graph(deps: AgentDependencies):
    """
    构建并编译 Agent 状态图。

    Args:
        deps: AgentDependencies 依赖容器

    Returns:
        编译后的 LangGraph 状态图（Runnable），可调用 invoke(initial_state)
    """
    try:
        from langgraph.graph import StateGraph, START, END
    except ImportError as e:
        raise ImportError(
            "langgraph 未安装，请执行 pip install langgraph"
        ) from e

    tool_infos = deps.tool_registry.list_tool_infos() if deps.tool_registry else []

    planner = make_planner_node(
        llm_client=deps.llm_client,
        tool_infos=tool_infos,
        max_plan_steps=deps.max_plan_steps,
        knowledge_base_ids=deps.knowledge_base_ids,
        get_long_term_context=deps.get_long_term_context,
    )
    executor = make_executor_node(deps.tool_registry, deps.knowledge_base_ids)
    reflector = make_reflector_node(deps.llm_client, deps.max_retry)
    responder = make_responder_node(deps.llm_client)

    def route_after_executor(state: dict) -> str:
        status = state.get("status")
        retry = state.get("retry_count", 0)
        if status == AgentTaskStatus.SUCCESS.value:
            return "responder"
        if status == AgentTaskStatus.FAILED.value:
            if retry < deps.max_retry:
                return "reflector"
            return "responder"
        return "responder"

    graph = StateGraph(AgentState)
    graph.add_node("planner", planner)
    graph.add_node("executor", executor)
    graph.add_node("reflector", reflector)
    graph.add_node("responder", responder)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")
    graph.add_conditional_edges(
        "executor",
        route_after_executor,
        {"responder": "responder", "reflector": "reflector"},
    )
    graph.add_edge("reflector", "planner")
    graph.add_edge("responder", END)

    compiled = graph.compile()
    logger.info("Agent 状态图构建完成")
    return compiled
