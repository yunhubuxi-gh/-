"""
响应节点：最终汇总响应

职责：
1. 汇总所有工具中间结果，调用 LLM 生成最终回答
2. 无中间结果或任务失败时，返回明确失败信息（禁止编造）
3. LLM 不可用时降级为拼接中间结果
"""
from __future__ import annotations

from typing import List, Dict, Any

from config.constants import AgentTaskStatus
from utils.logger import get_logger

logger = get_logger(__name__)

_RESPONDER_SYSTEM = (
    "你是任务执行助手。请基于下方工具执行结果，用中文简洁、准确地回答用户任务。"
    "只依据给定结果回答，不要编造结果之外的内容。"
)


def _summarize_results(intermediate_results: List[Dict[str, Any]]) -> str:
    """把中间结果拼接为可读文本"""
    lines = []
    for r in intermediate_results:
        tool = r.get("tool", "")
        data = r.get("data")
        if isinstance(data, str):
            text = data
        elif isinstance(data, dict):
            # 提取常见字段
            if "summary" in data:
                text = data["summary"]
            elif "results" in data:
                text = str(data["results"])
            elif "file_path" in data:
                text = f"已导出文件: {data['file_path']}"
            else:
                text = str(data)
        else:
            text = str(data)
        lines.append(f"[{tool}]\n{text}")
    return "\n\n".join(lines)


def make_responder_node(llm_client):
    """构造响应节点函数"""

    def responder_node(state: dict) -> dict:
        query: str = state.get("query", "")
        status: str = state.get("status", "")
        intermediate_results: List[Dict[str, Any]] = state.get("intermediate_results") or []
        last_error: str = state.get("last_error") or ""

        # 任务失败且无中间结果
        if status == AgentTaskStatus.FAILED.value and not intermediate_results:
            final_result = f"任务执行失败：{last_error or '未知错误'}"
            logger.warning(final_result)
            return {"final_result": final_result, "status": AgentTaskStatus.FAILED.value}

        # 无中间结果（异常情况，禁止编造）
        if not intermediate_results:
            final_result = "未获取到有效的工具执行结果，无法完成任务。"
            return {"final_result": final_result, "status": AgentTaskStatus.FAILED.value}

        context = _summarize_results(intermediate_results)

        # LLM 汇总
        if llm_client is not None:
            try:
                final_result = llm_client.chat([
                    {"role": "system", "content": _RESPONDER_SYSTEM},
                    {"role": "user", "content": f"【用户任务】\n{query}\n\n【工具执行结果】\n{context}"},
                ]).strip()
                if final_result:
                    return {"final_result": final_result, "status": AgentTaskStatus.SUCCESS.value}
            except Exception as e:
                logger.warning(f"LLM 汇总失败，降级为拼接结果: {e}")

        # 降级：直接返回拼接结果
        final_result = f"任务执行结果如下：\n\n{context}"
        return {"final_result": final_result, "status": AgentTaskStatus.SUCCESS.value}

    return responder_node
