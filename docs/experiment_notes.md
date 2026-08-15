# 毕设实验测试说明文档

本文档说明全套测试用例、核心功能的实验验证方法，以及 Mock（Fake）对象如何实现离线运行单元测试。

---

## 一、全套测试用例说明

项目按开发步骤配套 6 套测试脚本，覆盖六层架构各层，全部可离线运行（无需真实大模型 / 向量库 / 网络）。

### 测试总览

| 脚本 | 对应层 | 用例数（大项） | 核心验证点 |
|------|--------|--------------|-----------|
| `tests/test_step1_utils.py` | Utils 工具层 | 多组 | 密码哈希、JWT 签发/校验、文件安全、统一响应、错误码 |
| `tests/test_step2_db.py` | 数据库层 | 多组 | ORM 模型、CRUD、密码哈希、软删除、权限关系 |
| `tests/test_step3_rag.py` | RAG 引擎层 | 9 项 | 解析/分块/入库/多路召回/重排/引用/幻觉抑制/问答入口 |
| `tests/test_step4_agent.py` | Agent 智能层 | 6 项 | 状态图/工具集分类/记忆/成功执行/反思重试/异常审计 |
| `tests/test_step5_services.py` | 业务服务层 | 6 项 | 注册登录/权限隔离/上传向量化/RAG问答/Agent提交/审计 |
| `tests/test_step6_api.py` | API 接口层 | 6 项 | 登录鉴权/权限拦截/异步上传/问答/Agent/异常格式 |

### 运行方式

```bash
# 单个运行
python tests/test_step3_rag.py

# 全部运行
python tests/test_step1_utils.py
python tests/test_step2_db.py
python tests/test_step3_rag.py
python tests/test_step4_agent.py
python tests/test_step5_services.py
python tests/test_step6_api.py
```

> 每个脚本末尾输出「测试结果: 共 N 大项, 通过 N 项, 失败 0 项」，通过即 🎉 提示。

---

## 二、混合 RAG 召回效果测试说明

**验证目标**：证明「BM25 + 向量 + 重排」混合召回优于单一召回方式。

### 实现机制（对应代码）

1. **多路召回**：`ai/rag_engine/hybrid_retriever.py` 的 `HybridRetriever.retrieve` 同时触发
   - 向量召回：`vector_store.search`（BGE 嵌入余弦相似度）
   - BM25 召回：`bm25_engine.search`（jieba 分词 + BM25 打分）
2. **融合**：`_fuse` 对两路分数分别 min-max 归一化，按权重（向量 0.7 + BM25 0.3）加权，按 chunk_id 去重。
3. **精排**：`reranker` 对融合结果二次打分，取 top_k。

### 测试用例（test_step3 第 5 项）

- 向知识库写入若干 chunk（含关键句），用确定性问题检索；
- 断言：返回结果命中关键 chunk、分数合理、BM25 与向量两路都参与；
- 验证重排后排序优于融合前。

### 实验建议（论文实验章节）

- 构造含同义词/改写表达的查询，对比「仅 BM25」「仅向量」「混合」「混合+重排」四组 Top-K 命中率（Recall@K）与 MRR；
- 用不同文档类型（制度/手册/合同）验证鲁棒性。

---

## 三、Agent 失败反思重试逻辑测试说明

**验证目标**：证明 Agent 任务失败时能自动分析原因、修正策略并重试，且受重试上限约束不陷入死循环。

### 实现机制（对应代码）

- `ai/agent_langgraph/graph_builder.py`：`planner → executor → 条件路由 → reflector → planner` 闭环；
- `executor_node`：任一工具失败立即停止，写 `last_error`，状态置 `FAILED`；
- 条件路由：`FAILED` 且 `retry_count < max_retry` → 进入 `reflector` 反思；`retry_count >= max_retry` → 直接 `responder` 结束；
- `reflector_node`：分析失败原因、生成修正策略，`retry_count + 1`。

### 测试用例（test_step4 第 5 项）

- 注入 `FakeRagPipeline(fail=True)` 让工具持续失败；
- 断言：最终状态 `failed`、`retry_count <= max_retry`（防死循环）、工具被多次调用（每次重试重新执行）。

### 实验建议

- 构造「检索无结果 → 反思调整关键词 → 重试命中」的成功路径，统计重试后成功率提升；
- 对比「无反思直接失败」与「反思重试」的任务成功率。

---

## 四、知识库越权拦截测试说明

**验证目标**：证明四级 RBAC 权限（owner/admin/write/read）拦截有效，越权操作被拒绝并写审计。

### 实现机制（对应代码）

- `utils/permission.py`：`has_permission` 按等级数值比较（owner=100 > admin=80 > write=50 > read=20）；
- `services/kb_service.py` / `document_service.py` / `chat_service.py`：每个操作先 `kb_crud.get_user_role` 取角色，再 `has_permission` 校验，不足抛 `PermissionException(KB_NO_PERMISSION)` 并写审计 `permission_denied`。

### 测试用例

- test_step5 第 2 项：owner 建库 + 添加成员（write/read），reader 越权加成员被拦截、非成员访问被拦截、owner 更新成员权限；
- test_step5 第 3 项：read 用户越权上传文档被拦截；
- test_step5 第 6 项：越权操作产生 `permission_denied` 审计记录；
- test_step6 第 2 项：HTTP 层非成员访问知识库返回 403 + 错误码 1200003。

---

## 五、Mock 假对象实现离线测试说明

**设计目标**：单元测试不依赖真实大模型 API、向量数据库、网络下载，实现秒级、确定、可复现的离线运行。

### 核心 Fake 组件

| Fake 类 | 模拟对象 | 作用 |
|---------|---------|------|
| `FakeLLM` | `utils.llm_client.LLMClient` | 根据 system prompt 返回固定规划/反思/回答文本；`fail=True` 时抛异常 |
| `FakeRagPipeline` | `ai.rag_engine.RagPipeline` | 模拟 `ingest_document` / `answer`，返回固定 `RagAnswer`（含 Citation） |
| `FakeAgentManager` | `ai.agent_langgraph.AgentManager` | 模拟 `execute`，返回固定 `AgentExecutionResult`，同时写 agent_tasks 表 |
| `FakeEmbedder` / `HashingEmbedder` | 嵌入客户端 | 用 MD5 哈希生成确定性向量，避免加载 BGE 模型 |
| `FakeVectorStore` | 向量库 | 内存字典模拟 upsert/search |

### 注入方式

通过构造器依赖注入把 Fake 传入真实组件：

```python
# 示例（test_step5 文档上传）
fake = FakeRagPipeline()
svc = DocumentService(rag_pipeline=fake)   # 注入 Fake，避免真实向量化

# 示例（test_step4 Agent）
manager = AgentManager(llm_client=FakeLLM(), rag_pipeline=FakeRagPipeline())
```

### 测试数据库

- 使用 SQLite 临时文件库（WAL 模式 + NullPool），`Base.metadata.create_all` 建表，测试结束自动丢弃；
- 避免使用真实 PostgreSQL，保证测试可离线、可重复。

### 关键设计：确定性 + 离线

1. **确定性**：Fake 返回固定内容，`HashingEmbedder` 用哈希生成稳定向量，测试结果可复现；
2. **离线**：不 import 真实 `sentence-transformers` / `FlagEmbedding` / `chromadb` 下载模型，全部 Fake 替代；
3. **真实逻辑仍被测试**：LangGraph 状态图、权限校验、审计落库、RAG 编排逻辑均走真实实现，仅替换最底层依赖。

---

## 六、PaddleOCR 可选组件启用说明

PaddleOCR 是**可选依赖**，用于扫描版 PDF 的文字识别，**Docker 默认不安装**（体积大，且代码内已做优雅降级——未安装时扫描件 PDF 跳过 OCR）。

### 手动启用方式

```bash
# 1. 取消 requirements.txt 中以下两行注释
# paddleocr==3.2.0
# paddlepaddle==3.1.1

# 2. 重新安装依赖
pip install -r requirements.txt

# 3. 确认 .env 中 OCR 配置开启（默认已开启）
# OCR_ENABLED=true
# OCR_ENGINE=paddleocr
# OCR_LANG=ch

# 4. Docker 部署启用：需在 Dockerfile 中追加 paddleocr/paddlepaddle 安装，
#    并重新构建镜像（默认镜像为精简体积不含 OCR）
```

> 本地开发若要启用，直接 `pip install paddleocr paddlepaddle` 即可，代码 `utils/ocr_engine.py` 会自动检测并加载。
