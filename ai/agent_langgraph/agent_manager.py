"""
Agent 管理器（统一执行入口）

对外暴露统一 Agent 执行入口 execute()：
    入参：用户 id、会话 id、任务指令、授权知识库 id 列表
    出参：执行结果 + 工具调用历史记录

职责：
1. 组装依赖（LLM / 工具 / 记忆 / RAG pipeline），全部懒加载 + 可注入
2. 构建 LangGraph 状态图并执行规划-执行-反思闭环
3. 将任务状态/规划/执行日志/反思日志/结果写入 agent_tasks 表（DB 提供时）
4. 调用 utils.logger.log_audit 写审计日志（禁止自己实现日志）
5. 捕获工具/大模型异常，返回标准化错误对象
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import List, Any, Optional

from ai.agent_langgraph.agent_config import get_agent_config
from ai.agent_langgraph.graph_builder import AgentDependencies, build_agent_graph
from ai.agent_langgraph.state import AgentState
from ai.agent_langgraph.memory import ShortTermMemory, LongTermMemory
from config.constants import AgentTaskStatus, AuditAction, AuditResult
from utils.logger import get_logger, log_audit
from utils.exceptions import AgentException
from utils.error_codes import AGENT_TASK_FAILED

logger = get_logger(__name__)


@dataclass
class AgentExecutionResult:
    """Agent 执行结果（标准化输出）"""
    task_id: str
    status: str
    result: Optional[str] = None
    tool_history: List[dict] = field(default_factory=list)
    retry_count: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.status == AgentTaskStatus.SUCCESS.value

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "result": self.result,
            "tool_history": self.tool_history,
            "retry_count": self.retry_count,
            "error": self.error,
            "success": self.success,
        }


class AgentManager:
    """
    Agent 管理器。

    依赖均可通过构造器注入（测试用 Fake），缺省时懒加载真实组件。
    """

    def __init__(
        self,
        llm_client=None,
        rag_pipeline=None,
        tool_registry=None,
        short_memory=None,
        long_memory=None,
    ):
        self.llm_client = llm_client
        self.rag_pipeline = rag_pipeline
        self.tool_registry = tool_registry
        self.short_memory = short_memory
        self.long_memory = long_memory
        self.config = get_agent_config()

    # ---------- 懒加载依赖 ----------

    def _get_llm(self):
        if self.llm_client is None:
            try:
                from utils.llm_client import get_llm_client
                self.llm_client = get_llm_client()
            except Exception as e:
                logger.warning(f"LLM 客户端初始化失败，降级为无 LLM 模式: {e}")
                self.llm_client = None
        return self.llm_client

    def _get_rag_pipeline(self):
        if self.rag_pipeline is None:
            from ai.rag_engine.rag_pipeline import RagPipeline
            self.rag_pipeline = RagPipeline()
        return self.rag_pipeline

    def _get_tool_registry(self):
        if self.tool_registry is None:
            from ai.agent_langgraph.tools.registry import build_default_registry
            self.tool_registry = build_default_registry(
                rag_pipeline=self._get_rag_pipeline(),
                llm_client=self._get_llm(),
            )
        return self.tool_registry

    def _get_short_memory(self):
        if self.short_memory is None:
            self.short_memory = ShortTermMemory()
        return self.short_memory

    def _get_long_memory(self):
        if self.long_memory is None:
            self.long_memory = LongTermMemory()
        return self.long_memory

    # ---------- 统一执行入口 ----------

    def execute(
        self,
        user_id: int,
        task_input: str,
        knowledge_base_ids: List[Any],
        conversation_id: Optional[int] = None,
        db=None,
        title: Optional[str] = None,
    ) -> AgentExecutionResult:
        """
        统一 Agent 执行入口。

        Args:
            user_id: 用户 ID
            task_input: 用户任务指令
            knowledge_base_ids: 授权知识库 ID 列表
            conversation_id: 会话 ID（可选）
            db: SQLAlchemy Session（可选，提供时写入任务状态与审计表）
            title: 任务标题（可选）

        Returns:
            AgentExecutionResult
        """
        task_id = uuid.uuid4().hex
        start_time = time.time()

        # 1. 创建任务记录（DB）
        if db is not None:
            self._create_task_record(db, user_id, task_id, task_input, knowledge_base_ids,
                                     conversation_id, title)

        try:
            # 2. 检索长期记忆
            long_term_context = self._retrieve_long_term(user_id, task_input)

            # 3. 构建并运行状态图
            deps = AgentDependencies(
                llm_client=self._get_llm(),
                tool_registry=self._get_tool_registry(),
                knowledge_base_ids=list(knowledge_base_ids),
                max_retry=self.config.max_retry,
                max_plan_steps=self.config.max_plan_steps,
                get_long_term_context=lambda q: self._retrieve_long_term(user_id, q),
            )
            graph = build_agent_graph(deps)

            initial_state: AgentState = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "knowledge_base_ids": list(knowledge_base_ids),
                "query": task_input,
                "task_id": task_id,
                "plan": [],
                "current_step": 0,
                "tool_history": [],
                "intermediate_results": [],
                "retry_count": 0,
                "last_error": None,
                "reflection": None,
                "status": AgentTaskStatus.PENDING.value,
                "final_result": None,
                "long_term_context": long_term_context,
            }

            final_state = graph.invoke(initial_state)

            # 4. 提取结果
            result = AgentExecutionResult(
                task_id=task_id,
                status=final_state.get("status", AgentTaskStatus.FAILED.value),
                result=final_state.get("final_result"),
                tool_history=final_state.get("tool_history", []),
                retry_count=final_state.get("retry_count", 0),
            )

            # 5. 更新任务记录（DB）
            if db is not None:
                self._update_task_result(db, task_id, final_state, result, start_time)

            # 6. 审计日志
            self._audit(db, user_id, task_id, result, task_input)

            return result

        except AgentException:
            raise
        except Exception as e:
            # 捕获工具/大模型/图构建等异常，返回标准化错误对象
            logger.error(f"Agent 执行异常: {e}")
            error_result = AgentExecutionResult(
                task_id=task_id,
                status=AgentTaskStatus.FAILED.value,
                result=None,
                tool_history=[],
                retry_count=0,
                error=f"Agent 执行失败: {e}",
            )
            if db is not None:
                self._mark_failed(db, task_id, str(e))
            self._audit(db, user_id, task_id, error_result, task_input)
            return error_result

    # ---------- 记忆 ----------

    def _retrieve_long_term(self, user_id: int, query: str) -> List[str]:
        try:
            return self._get_long_memory().retrieve(user_id, query=query)
        except Exception as e:
            logger.warning(f"长期记忆检索失败: {e}")
            return []

    # ---------- DB 任务记录 ----------

    @staticmethod
    def _create_task_record(db, user_id, task_id, task_input, kb_ids, conversation_id, title):
        from db.crud import agent_task_crud
        from db.schemas import AgentTaskCreate
        try:
            agent_task_crud.create(
                db,
                user_id,
                AgentTaskCreate(
                    task_input=task_input,
                    conversation_id=conversation_id,
                    knowledge_base_id=kb_ids[0] if kb_ids else None,
                    title=title,
                ),
                task_id=task_id,
            )
        except Exception as e:
            logger.warning(f"创建任务记录失败: {e}")

    @staticmethod
    def _update_task_result(db, task_id, final_state, result, start_time):
        from db.crud import agent_task_crud
        try:
            plan = final_state.get("plan") or []
            tool_history = final_state.get("tool_history") or []
            duration_ms = int((time.time() - start_time) * 1000)

            if plan:
                agent_task_crud.update_plan(db, task_id, plan)
            for step_log in tool_history:
                agent_task_crud.append_execution_log(db, task_id, step_log)
            if result.retry_count > 0:
                agent_task_crud.append_reflection_log(db, task_id, {
                    "retry": result.retry_count,
                    "issue": final_state.get("last_error", ""),
                    "strategy": final_state.get("reflection", ""),
                })

            if result.success:
                agent_task_crud.set_result(
                    db, task_id, result.result or "",
                    result_data={"tool_history": result.tool_history},
                    duration_ms=duration_ms,
                )
            else:
                agent_task_crud.update_status(
                    db, task_id, AgentTaskStatus.FAILED.value, result.error
                )
        except Exception as e:
            logger.warning(f"更新任务结果失败: {e}")

    @staticmethod
    def _mark_failed(db, task_id, error):
        from db.crud import agent_task_crud
        try:
            agent_task_crud.update_status(db, task_id, AgentTaskStatus.FAILED.value, error)
        except Exception as e:
            logger.warning(f"标记任务失败失败: {e}")

    # ---------- 审计 ----------

    @staticmethod
    def _audit(db, user_id, task_id, result: AgentExecutionResult, task_input: str):
        """写审计日志：文件审计（utils.logger.log_audit）+ 数据库审计（audit_log_crud）"""
        audit_result = AuditResult.SUCCESS.value if result.success else AuditResult.FAILED.value
        action = (
            AuditAction.AGENT_TASK_COMPLETE.value if result.success
            else AuditAction.AGENT_TASK_COMPLETE.value
        )

        # 文件审计（权威，禁止自己实现日志）
        log_audit(
            user_id=str(user_id),
            action=action,
            resource=f"agent_task_{task_id}",
            result=audit_result,
            details=f"task={task_input[:50]} | retry={result.retry_count} | error={result.error or ''}",
        )

        # 数据库审计（DB 提供时）
        if db is not None:
            try:
                from db.crud import audit_log_crud
                audit_log_crud.create(
                    db,
                    user_id=user_id,
                    action=action,
                    result=audit_result,
                    resource_type="agent_task",
                    resource_id=task_id,
                    details={"task_input": task_input[:200], "retry_count": result.retry_count},
                    error_message=result.error,
                )
            except Exception as e:
                logger.warning(f"写数据库审计日志失败: {e}")
