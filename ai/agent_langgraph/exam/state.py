"""
试卷双 Agent 工作流 State 定义

保存一次「命题 → 校验 → 重生成」闭环执行过程中的全部状态：
- 课程库上下文（knowledge_base_id）
- 题型配置 question_config 与难度 difficulty
- 当前试卷题目 questions（含答案/知识点/来源引用）
- 本轮校验结果 validation_results 与不合格题 rejected_questions
- 迭代计数 iterate_count / 上限 max_iterate
- 完整执行轨迹 trace（追加，Annotated + operator.add）
"""
from __future__ import annotations

import operator
from typing import TypedDict, Annotated, List, Dict, Any, Optional


class ExamState(TypedDict, total=False):
    # ---- 上下文 ----
    knowledge_base_id: int                    # 课程库 ID
    question_config: Dict[str, int]           # {choice, fill, short}
    difficulty: str                           # easy/medium/hard

    # ---- 命题结果 ----
    questions: List[Dict[str, Any]]           # 当前试卷题目（含答案/知识点/来源引用）
    rejected_questions: List[Dict[str, Any]]  # 本轮校验不合格的题（回传命题 Agent 重生成）

    # ---- 校验结果 ----
    validation_results: List[Dict[str, Any]]  # 本轮逐题校验结果

    # ---- 迭代 ----
    iterate_count: int                        # 当前已完成的生成轮数
    max_iterate: int                          # 最大迭代次数（防死循环）

    # ---- 轨迹（追加语义）----
    trace: Annotated[List[Dict[str, Any]], operator.add]

    # ---- 结果 ----
    status: str                               # generating / validating / done
    error: Optional[str]
