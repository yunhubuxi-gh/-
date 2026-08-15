"""
步骤4 - Agent LangGraph 智能层 测试脚本

覆盖：状态图 State、工具集两类、记忆模块（短期裁剪/长期复用）、
统一执行入口、失败反思重试（重试上限）、异常处理 + 审计日志。

设计说明：
- 注入 FakeLLM / FakeRagPipeline，避免依赖真实大模型与向量库，离线可跑
- LangGraph 走真实实现（已安装 langgraph）
- DB 审计用 SQLite 内存库验证

运行方式：
    pip install langgraph
    python tests/test_step4_agent.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.rag_engine.hybrid_retriever import RetrievedChunk


# ============================================================
# 测试用 Fake 组件
# ============================================================

class FakeLLM:
    """根据 system prompt 区分 planner/reflector/responder/summary 调用"""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.call_count = 0

    def chat(self, messages, **kwargs):
        if self.fail:
            raise RuntimeError("大模型服务异常")
        self.call_count += 1
        system = messages[0]["content"] if messages else ""
        if "任务规划器" in system:
            return '[{"step": 1, "tool": "kb_search", "input": {"query": "请假流程"}, "description": "检索知识库"}]'
        if "反思分析器" in system:
            return "失败原因：检索无结果；修正策略：调整关键词重试。"
        if "任务执行助手" in system:
            return "根据知识库，员工请假需提前三天提交申请。"
        if "文档摘要" in system:
            return "文档摘要：员工请假流程。"
        return "默认回答"


class FakeRagPipeline:
    """模拟 rag_engine 统一检索入口（返回 RetrievedChunk）"""

    def __init__(self, fail: bool = False):
        self.fail = fail

    def retrieve(self, query, knowledge_base_ids=None, top_k=5, **kwargs):
        if self.fail:
            raise RuntimeError("向量库检索失败")
        return [
            RetrievedChunk(
                chunk_id="doc_1:0",
                document_id="1",
                knowledge_base_id="kb_1",
                content="员工请假需提前三天提交申请，并经过部门主管审批。",
                score=0.9,
                page_number=1,
                chunk_index=0,
                metadata={"document_name": "员工手册.pdf"},
            )
        ]


class FakeEmbedder:
    """确定性假嵌入（避免长期记忆测试触发真实 BGE 模型加载）"""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def _vec(self, text: str):
        import hashlib
        vec = [0.0] * self.dim
        for tok in list(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        import math
        norm = math.sqrt(sum(x * x for x in vec))
        if norm:
            vec = [x / norm for x in vec]
        return vec

    def embed(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, query: str):
        return self._vec(query)


def setup_test_db():
    """初始化 SQLite 内存库（用于审计/任务表验证）"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import db.session as db_session

    engine = create_engine("sqlite:///:memory:", echo=False, connect_args={"check_same_thread": False})
    db_session.sync_engine = engine
    db_session.SyncSessionLocal = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )
    from db.base import Base
    from db import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    return engine


def _build_manager(llm=None, rag=None, registry=None, long_memory=None):
    from ai.agent_langgraph.agent_manager import AgentManager
    return AgentManager(
        llm_client=llm,
        rag_pipeline=rag,
        tool_registry=registry,
        long_memory=long_memory,
    )


# ============================================================
# 测试函数
# ============================================================

def test_1_state_and_config():
    """测试状态图 State 定义 + 配置化"""
    print("\n" + "=" * 60)
    print("【测试1】State 定义 + 配置")
    print("=" * 60)

    from ai.agent_langgraph.state import AgentState
    from ai.agent_langgraph.agent_config import get_agent_config

    # State 关键字段
    required_fields = {
        "user_id", "conversation_id", "knowledge_base_ids", "query",
        "tool_history", "intermediate_results", "retry_count", "final_result",
    }
    assert required_fields.issubset(set(AgentState.__annotations__)), "State 缺少关键字段"
    print(f"  ✓ State 字段齐全: {sorted(AgentState.__annotations__.keys())}")

    # 配置化
    cfg = get_agent_config()
    assert cfg.max_retry >= 1
    assert cfg.short_term_window >= 1
    assert cfg.long_term_max_items >= 1
    print(f"  ✓ 配置: max_retry={cfg.max_retry}, window={cfg.short_term_window}, "
          f"long_term_max={cfg.long_term_max_items}")
    print("  ✅ State + 配置 通过")


def test_2_tool_registry():
    """测试工具集两类（内部 RAG + 外部业务）"""
    print("\n" + "=" * 60)
    print("【测试2】工具集分类")
    print("=" * 60)

    from ai.agent_langgraph.tools.registry import build_default_registry
    from ai.agent_langgraph.tools.base_tool import ToolCategory

    registry = build_default_registry(
        rag_pipeline=FakeRagPipeline(),
        llm_client=FakeLLM(),
    )
    names = registry.list_tool_names()
    assert "kb_search" in names
    assert "doc_summary" in names
    assert "export_csv" in names
    print(f"  ✓ 工具列表: {names}")

    # 分类
    assert registry.get("kb_search").category == ToolCategory.INTERNAL_RAG
    assert registry.get("doc_summary").category == ToolCategory.EXTERNAL_BIZ
    assert registry.get("export_csv").category == ToolCategory.EXTERNAL_BIZ
    print(f"  ✓ kb_search 属于内部 RAG，doc_summary/export_csv 属于外部业务")

    # kb_search 能正确调用 rag_engine 统一入口
    kb_tool = registry.get("kb_search")
    result = kb_tool.run(query="请假流程", knowledge_base_id=None)
    assert result["status"] == "success"
    assert result["data"]["total"] == 1
    assert result["data"]["results"][0]["document_name"] == "员工手册.pdf"
    print(f"  ✓ kb_search 调用 rag_engine 统一入口成功: 返回 {result['data']['total']} 条")

    # export_csv 真实写文件
    with tempfile.TemporaryDirectory() as tmp:
        from ai.agent_langgraph.tools.external.export_csv_tool import ExportCsvTool
        csv_tool = ExportCsvTool(export_dir=tmp)
        csv_result = csv_tool.run(data=[{"a": 1, "b": 2}], filename="test")
        assert csv_result["status"] == "success"
        assert os.path.exists(csv_result["data"]["file_path"])
        print(f"  ✓ export_csv 成功写出文件: {csv_result['data']['file_path']}")

    print("  ✅ 工具集分类 通过")


def test_3_memory():
    """测试记忆模块（短期裁剪 + 长期复用裁剪）"""
    print("\n" + "=" * 60)
    print("【测试3】记忆模块")
    print("=" * 60)

    from ai.agent_langgraph.memory import ShortTermMemory, LongTermMemory

    # 短期记忆：滑动窗口裁剪
    stm = ShortTermMemory(window=5)
    for i in range(10):
        stm.add("user", f"消息{i}")
    assert len(stm) == 5, f"短期记忆应裁剪到 5 条，实际 {len(stm)}"
    ctx = stm.get_context()
    assert ctx[0]["content"] == "消息5"  # 保留最近 5 条
    print(f"  ✓ 短期记忆滑动窗口裁剪: 10 -> {len(stm)} 条，最旧消息被丢弃")

    # 长期记忆：保存 + 裁剪 + 复用
    with tempfile.TemporaryDirectory() as tmp:
        ltm = LongTermMemory(enabled=True, max_items=3, storage_dir=tmp,
                             embedding_client=FakeEmbedder())
        for i in range(5):
            ltm.save_preference(user_id=1, content=f"偏好{i}")
        all_prefs = ltm.get_all(1)
        assert len(all_prefs) == 3, f"长期记忆应裁剪到 3 条，实际 {len(all_prefs)}"
        print(f"  ✓ 长期记忆条数上限裁剪: 5 -> {len(all_prefs)} 条")

        # 跨会话复用（重新实例化从磁盘加载）
        ltm2 = LongTermMemory(enabled=True, max_items=3, storage_dir=tmp,
                              embedding_client=FakeEmbedder())
        assert len(ltm2.get_all(1)) == 3
        print(f"  ✓ 长期记忆跨实例持久化复用成功")

        # 检索（向量相似度）
        ltm3 = LongTermMemory(enabled=True, max_items=3, storage_dir=tmp,
                              embedding_client=FakeEmbedder())
        retrieved = ltm3.retrieve(user_id=1, query="偏好2", top_k=1)
        assert len(retrieved) >= 1
        print(f"  ✓ 长期记忆检索: {retrieved}")

    print("  ✅ 记忆模块 通过")


def test_4_execute_success():
    """测试统一执行入口（成功路径）"""
    print("\n" + "=" * 60)
    print("【测试4】统一执行入口（成功）")
    print("=" * 60)

    manager = _build_manager(llm=FakeLLM(), rag=FakeRagPipeline())
    result = manager.execute(
        user_id=1,
        task_input="请假流程是什么？",
        knowledge_base_ids=[1],
        conversation_id=None,
    )

    assert result.success, f"应执行成功，实际 status={result.status}"
    assert result.result is not None
    assert len(result.tool_history) >= 1
    # 工具历史记录结构
    first = result.tool_history[0]
    assert first["tool"] == "kb_search"
    assert first["status"] == "success"
    print(f"  ✓ 执行结果: status={result.status}, retry={result.retry_count}")
    print(f"  ✓ 最终回答: {result.result}")
    print(f"  ✓ 工具调用历史: {[(t['tool'], t['status']) for t in result.tool_history]}")
    print("  ✅ 统一执行入口（成功）通过")


def test_5_retry_on_failure():
    """测试工具失败 → 自动反思重试（受重试上限约束）"""
    print("\n" + "=" * 60)
    print("【测试5】失败反思重试")
    print("=" * 60)

    manager = _build_manager(llm=FakeLLM(), rag=FakeRagPipeline(fail=True))
    result = manager.execute(
        user_id=1,
        task_input="请假流程是什么？",
        knowledge_base_ids=[1],
    )

    from ai.agent_langgraph.agent_config import get_agent_config
    max_retry = get_agent_config().max_retry

    # 最终失败（工具一直失败）
    assert result.status == "failed"
    # 重试次数不超过上限（防死循环）
    assert result.retry_count <= max_retry, f"重试次数 {result.retry_count} 超过上限 {max_retry}"
    # 工具被多次调用（每次重试都重新执行）
    assert len(result.tool_history) >= 1
    print(f"  ✓ 工具失败后自动重试: retry_count={result.retry_count}（上限 {max_retry}）")
    print(f"  ✓ 工具调用历史 {len(result.tool_history)} 条（含失败重试记录）")
    print(f"  ✓ 最终状态: {result.status}")
    print("  ✅ 失败反思重试 通过")


def test_6_exception_and_audit():
    """测试异常处理 + 审计日志（DB）"""
    print("\n" + "=" * 60)
    print("【测试6】异常处理 + 审计日志")
    print("=" * 60)

    setup_test_db()
    from db.session import SyncSessionLocal

    # 场景1：LLM 异常，Agent 应降级（默认计划 + 拼接结果）不崩溃
    manager = _build_manager(llm=FakeLLM(fail=True), rag=FakeRagPipeline())
    db = SyncSessionLocal()
    result = manager.execute(
        user_id=1,
        task_input="请假流程是什么？",
        knowledge_base_ids=[1],
        db=db,
    )
    assert result is not None
    assert isinstance(result.to_dict(), dict)
    assert result.success, f"LLM 异常时应降级成功，实际 status={result.status}"
    print(f"  ✓ LLM 异常时 Agent 降级不崩溃: status={result.status}")

    # 验证任务表记录
    from db.crud import agent_task_crud
    task = agent_task_crud.get_by_task_id(db, result.task_id)
    assert task is not None
    print(f"  ✓ agent_tasks 表记录写入: task_id={task.task_id[:12]}..., status={task.status}")

    # 验证审计日志表记录
    from db.crud import audit_log_crud
    logs, total = audit_log_crud.query(db, resource_id=result.task_id)
    assert total >= 1, "审计日志应至少写入 1 条"
    assert logs[0].action in ("agent_task_complete", "agent_task_create")
    print(f"  ✓ 审计日志写入: action={logs[0].action}, result={logs[0].result}")

    # 场景2：检索失败（异常），带 db，验证失败审计
    db2 = SyncSessionLocal()
    manager2 = _build_manager(llm=FakeLLM(), rag=FakeRagPipeline(fail=True))
    result2 = manager2.execute(
        user_id=2,
        task_input="检索失败测试",
        knowledge_base_ids=[1],
        db=db2,
    )
    assert result2.status == "failed"
    logs2, total2 = audit_log_crud.query(db2, resource_id=result2.task_id)
    assert total2 >= 1
    assert logs2[0].result == "failed"
    print(f"  ✓ 失败场景审计: result={logs2[0].result}, 任务状态={result2.status}")

    db.close()
    db2.close()
    print("  ✅ 异常处理 + 审计日志 通过")


def main():
    print("\n" + "🚀" * 10 + " 步骤4 Agent LangGraph 模块测试开始 " + "🚀" * 10)

    tests = [
        test_1_state_and_config,
        test_2_tool_registry,
        test_3_memory,
        test_4_execute_success,
        test_5_retry_on_failure,
        test_6_exception_and_audit,
    ]

    passed = 0
    failed = 0
    for test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n  ❌ 测试失败: {test_func.__name__}")
            print(f"     错误: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"测试结果: 共 {len(tests)} 大项, 通过 {passed} 项, 失败 {failed} 项")
    print("=" * 60)

    if failed == 0:
        print("🎉 全部测试通过！步骤4 Agent LangGraph 模块正常。")
        print()
        print("🤖 Agent 模块清单:")
        print("  agent_config.py       Agent 配置（重试次数/记忆窗口全配置化）")
        print("  state.py             状态图 State（query/工具历史/重试计数/会话/用户）")
        print("  graph_builder.py     LangGraph 状态图（规划→执行→反思循环）")
        print("  nodes/planner_node.py      任务拆解规划节点")
        print("  nodes/executor_node.py     工具执行节点")
        print("  nodes/reflector_node.py    反思节点（失败重试）")
        print("  nodes/responder_node.py    汇总响应节点")
        print("  tools/               工具集（内部 RAG 检索 + 外部摘要/CSV）")
        print("  memory/              记忆（短期滑动窗口 + 长期偏好复用）")
        print("  agent_manager.py     统一执行入口（含审计日志）")
        print()
        print("✅ 关键能力验证:")
        print("   规划-执行-反思闭环 + 重试上限防死循环")
        print("   内部/外部工具分类 + 调用 rag_engine 统一入口")
        print("   短期记忆滑动窗口裁剪 / 长期记忆跨会话复用")
        print("   异常标准化返回 + utils.log_audit 审计日志")
    else:
        print(f"⚠️  有 {failed} 项测试失败。")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
