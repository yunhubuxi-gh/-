"""
规划节点：任务拆解与规划

职责：
1. 读取用户任务指令 query、可用工具、长期记忆、上次失败反思
2. 调用 LLM 生成子任务计划（JSON 列表），每个子任务指定工具与参数
3. LLM 不可用 / 解析失败时，降级为默认计划（直接知识库检索）

计划格式：
[{"step": 1, "tool": "kb_search", "input": {"query": "..."}, "description": "..."}]
"""
from __future__ import annotations

import json
import re
from typing import List, Dict, Any, Callable, Optional

from config.constants import AgentTaskStatus
from utils.logger import get_logger

logger = get_logger(__name__)

_PLANNER_SYSTEM = (
    "你是任务规划器。请把用户任务拆解为可执行的子任务，每个子任务指定一个工具。\n"
    "可用工具及其说明：\n{tool_desc}\n"
    "请严格输出 JSON 数组，格式：\n"
    '[{{"step": 1, "tool": "<工具名>", "input": {{...}}, "description": "<说明>"}}]\n'
    "只输出 JSON，不要输出其他内容。子任务数量不超过 {max_steps} 个。"
)


def _extract_json_array(text: str) -> List[dict]:
    """从 LLM 输出中提取 JSON 数组（兼容 markdown code fence）"""
    text = text.strip()
    # 去掉 ```json ... ``` 围栏
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        # 直接找第一个 [ 到最后一个 ]
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("计划必须是数组")
    return data


def _default_plan(query: str, kb_ids: List[Any]) -> List[Dict[str, Any]]:
    """默认降级计划：直接检索知识库（knowledge_base_id 需为字符串，对齐工具 schema）"""
    return [
        {
            "step": 1,
            "tool": "kb_search",
            "input": {"query": query, "knowledge_base_id": str(kb_ids[0]) if kb_ids else None},
            "description": "检索知识库获取相关信息",
        }
    ]


def make_planner_node(
    llm_client,
    tool_infos: List[dict],
    max_plan_steps: int,
    knowledge_base_ids: List[Any],
    get_long_term_context: Optional[Callable] = None,
):
    """
    构造规划节点函数。

    Args:
        llm_client: LLM 客户端（需实现 chat(messages) -> str）
        tool_infos: 工具元信息列表（registry.list_tool_infos()）
        max_plan_steps: 单次任务最大规划步骤数
        knowledge_base_ids: 授权知识库 ID 列表
        get_long_term_context: 长期记忆上下文获取函数（可选）
    """

    def planner_node(state: dict) -> dict:
        query = state.get("query", "")
        last_error = state.get("last_error")
        reflection = state.get("reflection")
        retry_count = state.get("retry_count", 0)

        # 长期记忆注入
        long_term_context: List[str] = state.get("long_term_context") or []
        if get_long_term_context is not None and not long_term_context:
            try:
                long_term_context = get_long_term_context(query) or []
            except Exception as e:
                logger.warning(f"长期记忆检索失败: {e}")
                long_term_context = []

        plan = None
        # 优先 LLM 规划
        if llm_client is not None:
            try:
                tool_desc = "\n".join(
                    f"- {t['name']}: {t['description']}" for t in tool_infos
                )
                system = _PLANNER_SYSTEM.format(tool_desc=tool_desc, max_steps=max_plan_steps)
                user_parts = [f"【用户任务】\n{query}"]
                if long_term_context:
                    user_parts.append(f"【用户历史偏好】\n" + "\n".join(long_term_context))
                if retry_count > 0:
                    user_parts.append(
                        f"【上次失败与修正建议】\n失败原因: {last_error}\n反思: {reflection}\n"
                        f"请调整工具参数或策略，重新规划。"
                    )
                user_msg = "\n\n".join(user_parts)

                raw = llm_client.chat([
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ])
                plan = _extract_json_array(raw)
                # 限制步骤数
                plan = plan[:max_plan_steps]
                # 规范化字段
                for i, step in enumerate(plan):
                    step.setdefault("step", i + 1)
                    step.setdefault("input", {})
                    step.setdefault("description", "")
            except Exception as e:
                logger.warning(f"LLM 规划失败，使用默认计划: {e}")
                plan = None

        if not plan:
            plan = _default_plan(query, knowledge_base_ids)

        logger.info(f"规划节点完成: 共 {len(plan)} 个子任务, retry={retry_count}")
        return {
            "plan": plan,
            "current_step": 0,
            "status": AgentTaskStatus.EXECUTING.value,
            "last_error": None,
            "reflection": None,
            "long_term_context": long_term_context,
        }

    return planner_node
