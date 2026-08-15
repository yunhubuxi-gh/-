"""
执行节点：工具调用执行

职责：
1. 按规划顺序执行每个子任务，从工具注册表获取工具并调用
2. 记录工具调用历史（tool_history）与成功的中间结果（intermediate_results）
3. 任一工具失败立即停止，写入错误信息，交由反思节点处理
"""
from __future__ import annotations

import time
from typing import List, Dict, Any

from config.constants import AgentTaskStatus
from utils.logger import get_logger

logger = get_logger(__name__)


def make_executor_node(tool_registry, knowledge_base_ids: List[Any]):
    """
    构造执行节点函数。

    Args:
        tool_registry: 工具注册表（ToolRegistry）
        knowledge_base_ids: 授权知识库 ID 列表（注入 kb_search 工具）
    """

    def executor_node(state: dict) -> dict:
        plan: List[Dict[str, Any]] = state.get("plan") or []
        current_step: int = state.get("current_step", 0)

        tool_history: List[Dict[str, Any]] = []
        intermediate_results: List[Dict[str, Any]] = []

        for idx in range(current_step, len(plan)):
            step = plan[idx]
            tool_name = step.get("tool", "")
            tool_input = step.get("input") or {}

            # 内部 RAG 工具：注入授权知识库 id（schema 为 str，需转字符串）
            if tool_name == "kb_search" and not tool_input.get("knowledge_base_id") and knowledge_base_ids:
                tool_input["knowledge_base_id"] = str(knowledge_base_ids[0])

            # 获取工具
            tool = tool_registry.get(tool_name) if tool_name else None
            if tool is None:
                err = f"工具不存在: {tool_name}"
                logger.warning(err)
                tool_history.append({
                    "step": idx + 1,
                    "tool": tool_name,
                    "input": tool_input,
                    "output": None,
                    "status": "failed",
                    "error": err,
                })
                return {
                    "tool_history": tool_history,
                    "intermediate_results": intermediate_results,
                    "current_step": idx,
                    "status": AgentTaskStatus.FAILED.value,
                    "last_error": err,
                }

            # 执行工具
            start = time.time()
            try:
                result = tool.run(**tool_input)
            except Exception as e:
                err = f"工具 {tool_name} 执行异常: {e}"
                logger.error(err)
                result = {"status": "failed", "data": None, "error": str(e)}

            duration_ms = int((time.time() - start) * 1000)
            status = result.get("status", "failed")
            output = result.get("data")
            error = result.get("error")

            entry = {
                "step": idx + 1,
                "tool": tool_name,
                "input": tool_input,
                "output": output,
                "status": status,
                "error": error,
                "duration_ms": duration_ms,
            }
            tool_history.append(entry)

            if status == "success":
                intermediate_results.append({
                    "step": idx + 1,
                    "tool": tool_name,
                    "data": output,
                })
            else:
                logger.warning(f"工具执行失败: tool={tool_name}, error={error}")
                return {
                    "tool_history": tool_history,
                    "intermediate_results": intermediate_results,
                    "current_step": idx,
                    "status": AgentTaskStatus.FAILED.value,
                    "last_error": error or f"工具 {tool_name} 执行失败",
                }

        # 全部执行成功
        logger.info(f"执行节点完成: {len(plan)} 个子任务全部成功")
        return {
            "tool_history": tool_history,
            "intermediate_results": intermediate_results,
            "current_step": len(plan),
            "status": AgentTaskStatus.SUCCESS.value,
            "last_error": None,
        }

    return executor_node
