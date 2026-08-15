"""
试卷双 Agent 管理器（统一执行入口）

对外暴露 execute()：
    入参：课程库 ID、题型配置、难度
    出参：最终试卷（题目 + 参考答案 + 完整执行轨迹 + 迭代次数）

职责：
1. 组装依赖（LLM / RAG pipeline），全部懒加载 + 可注入
2. 构建并运行「命题 → 校验 → 重生成」状态图
3. 提取最终试卷与轨迹，异常捕获返回标准化错误（不崩溃）

说明：本管理器只负责编排双 Agent 工作流，不写 DB、不写审计；
试卷/轨迹的持久化由上层 services.exam_service 完成。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config.settings import settings
from utils.logger import get_logger

from ai.agent_langgraph.exam.graph_builder import ExamDependencies, build_exam_graph
from ai.agent_langgraph.exam.state import ExamState

logger = get_logger(__name__)


class ExamManager:
    """试卷双 Agent 管理器（命题 + 校验评审）"""

    def __init__(self, llm_client=None, rag_pipeline=None):
        self.llm_client = llm_client
        self.rag_pipeline = rag_pipeline

    def _get_llm(self):
        if self.llm_client is None:
            from utils.llm_client import get_llm_client
            self.llm_client = get_llm_client()
        return self.llm_client

    def _get_rag_pipeline(self):
        if self.rag_pipeline is None:
            from ai.rag_engine.rag_pipeline import RagPipeline
            self.rag_pipeline = RagPipeline()
        return self.rag_pipeline

    def execute(
        self,
        knowledge_base_id: int,
        question_config: Dict[str, int],
        difficulty: str = "medium",
    ) -> Dict[str, Any]:
        """
        执行双 Agent 出卷闭环。

        Returns:
            {
                "questions": [...],
                "reference_answers": [...],
                "trace": [...],
                "iterate_count": int,
                "validation_results": [...],
                "total_score": int,
                "success": bool,
                "error": str | None,
                "warning": str | None,
            }
        """
        deps = ExamDependencies(
            llm_client=self._get_llm(),
            rag_pipeline=self._get_rag_pipeline(),
            max_iterate=int(settings.exam_max_iterate),
            llm_timeout=float(settings.exam_llm_timeout),
            llm_max_tokens=int(settings.exam_llm_max_tokens),
            rag_top_k=int(settings.exam_rag_top_k),
            temperature=float(settings.exam_temperature),
        )

        try:
            graph = build_exam_graph(deps)
            initial_state: ExamState = {
                "knowledge_base_id": int(knowledge_base_id),
                "question_config": question_config,
                "difficulty": difficulty,
                "questions": [],
                "rejected_questions": [],
                "validation_results": [],
                "iterate_count": 0,
                "max_iterate": deps.max_iterate,
                "trace": [],
                "status": "generating",
                "error": None,
            }
            final_state = graph.invoke(initial_state)
        except Exception as e:
            logger.error(f"试卷双 Agent 执行异常: {e}")
            return {
                "questions": [],
                "reference_answers": [],
                "trace": [],
                "iterate_count": 0,
                "validation_results": [],
                "total_score": 0,
                "success": False,
                "error": f"试卷生成失败: {e}",
                "warning": None,
            }

        questions = final_state.get("questions") or []
        rejected = final_state.get("rejected_questions") or []
        total_score = sum(int(q.get("score") or 0) for q in questions)

        warning: Optional[str] = None
        if rejected:
            warning = (
                f"达到最大迭代次数 {deps.max_iterate}，仍有 {len(rejected)} 题未通过校验，"
                "已按当前结果输出"
            )

        return {
            "questions": questions,
            "reference_answers": [
                {
                    "qid": q.get("qid"),
                    "answer": q.get("answer"),
                    "knowledge_point": q.get("knowledge_point"),
                }
                for q in questions
            ],
            "trace": final_state.get("trace") or [],
            "iterate_count": final_state.get("iterate_count", 0),
            "validation_results": final_state.get("validation_results") or [],
            "total_score": total_score,
            "success": bool(questions),
            "error": final_state.get("error"),
            "warning": warning,
        }
