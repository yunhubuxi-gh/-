"""
Agent 状态图 State 定义

保存一次 Agent 任务执行过程中的全部状态：
- 用户 / 会话 / 授权知识库 上下文
- 用户任务指令 query
- 规划结果 plan 与当前执行步骤 current_step
- 工具调用历史 tool_history（追加，Annotated + operator.add）
- 中间结果 intermediate_results（追加）
- 重试计数 retry_count 与最近错误 last_error
- 最终结果 final_result 与整体状态 status
- 注入的长期记忆上下文 long_term_context
"""
from __future__ import annotations

import operator
from typing import TypedDict, Annotated, List, Dict, Any, Optional


class AgentState(TypedDict, total=False):
    # ---- 上下文 ----
    user_id: int
    conversation_id: Optional[int]
    knowledge_base_ids: List[Any]           # 授权知识库 ID 列表
    query: str                               # 用户任务指令
    task_id: str                             # 业务任务 ID

    # ---- 规划 ----
    plan: List[Dict[str, Any]]               # [{step, tool, input, description}]
    current_step: int                        # 当前执行步骤索引

    # ---- 执行记录（追加语义）----
    tool_history: Annotated[List[Dict[str, Any]], operator.add]
    intermediate_results: Annotated[List[Dict[str, Any]], operator.add]

    # ---- 反思 / 重试 ----
    retry_count: int
    last_error: Optional[str]               # 最近一次工具/执行错误
    reflection: Optional[str]               # 反思结果（错误分析 + 修正策略）

    # ---- 结果 ----
    status: str                              # executing / success / failed
    final_result: Optional[str]

    # ---- 记忆 ----
    long_term_context: List[str]             # 检索到的长期偏好
