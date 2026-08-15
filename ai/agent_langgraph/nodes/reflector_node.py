"""
反思节点：结果校验与失败反思

职责：
1. 分析工具执行失败原因，调用 LLM 生成反思（错误分析 + 修正策略）
2. 重试计数 +1（重试上限由 config.agent_max_retry 控制，防死循环）
3. LLM 不可用时降级为启发式反思（调整查询措辞）
"""
from __future__ import annotations

from typing import List, Dict, Any

from config.constants import AgentTaskStatus
from utils.logger import get_logger

logger = get_logger(__name__)

_REFLECTOR_SYSTEM = (
    "你是反思分析器。工具执行失败，请分析失败原因并给出修正策略。\n"
    "只输出一段话，包含：1) 失败原因 2) 下一步如何调整工具参数或换用工具。"
)


def make_reflector_node(llm_client, max_retry: int):
    """
    构造反思节点函数。

    Args:
        llm_client: LLM 客户端（可为 None，降级为启发式反思）
        max_retry: 最大重试次数（超过则停止反思）
    """

    def reflector_node(state: dict) -> dict:
        retry_count: int = state.get("retry_count", 0)
        last_error: str = state.get("last_error", "") or "未知错误"
        query: str = state.get("query", "")
        tool_history: List[Dict[str, Any]] = state.get("tool_history") or []

        # 超过重试上限：不再反思，交由响应节点返回失败
        if retry_count >= max_retry:
            logger.warning(f"超过最大重试次数 {max_retry}，停止反思")
            return {
                "retry_count": retry_count,
                "status": AgentTaskStatus.FAILED.value,
                "reflection": "超过最大重试次数，任务失败",
            }

        new_retry = retry_count + 1

        # LLM 反思
        reflection = None
        if llm_client is not None:
            try:
                failed_tools = [t for t in tool_history if t.get("status") == "failed"]
                failed_desc = "\n".join(
                    f"- 工具 {t.get('tool')}: {t.get('error')}" for t in failed_tools
                )
                reflection = llm_client.chat([
                    {"role": "system", "content": _REFLECTOR_SYSTEM},
                    {"role": "user", "content": (
                        f"【用户任务】\n{query}\n"
                        f"【失败信息】\n{last_error}\n"
                        f"【失败工具】\n{failed_desc}"
                    )},
                ]).strip()
            except Exception as e:
                logger.warning(f"LLM 反思失败，使用启发式反思: {e}")
                reflection = None

        if not reflection:
            # 启发式降级反思
            reflection = f"上次执行失败（{last_error}），请尝试调整查询关键词或换用其他工具重试。"

        logger.info(f"反思节点完成: retry={new_retry}/{max_retry}")
        return {
            "retry_count": new_retry,
            "reflection": reflection,
            "status": AgentTaskStatus.EXECUTING.value,
        }

    return reflector_node
