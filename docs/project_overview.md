# 项目完整总览

> 企业私有知识库智能助手 —— 基于 RAG + LangGraph Agent 的企业级知识库问答与智能任务系统
> 适配方向：计算机专业（11408）本科毕业设计 · 简历求职演示

---

## 一、项目背景

企业内部沉淀了大量非结构化文档（制度、手册、SOP、合同等），员工检索与问答效率低。传统关键词检索无法理解语义，通用大模型无法访问企业私有数据且存在幻觉。本项目构建一套**私有化部署的 RAG + Agent 知识库系统**：

- **RAG 检索增强生成**：文档解析 → 语义分块 → 多路混合召回 → BGE 重排 → 幻觉抑制 → 引用溯源，实现"有据可查"的精准问答；
- **LangGraph 智能 Agent**：任务拆解 → 工具执行 → 反思重试的闭环，自主完成文档摘要、数据导出等复杂任务；
- **企业级工程化**：四级 RBAC 权限隔离、全链路审计日志、前后端分离、异步任务处理、Docker 一键部署。

系统面向真实企业内部使用场景，同时作为毕业设计与求职项目，覆盖完整的分层架构、可插拔设计、测试体系与部署方案。

---

## 二、完整六层架构详解

项目采用严格分层的六层架构（自下而上数据流、自上而下调用流），层间单向依赖、边界清晰：

```
┌────────────────────────────────────────────────────────────────┐
│  L7  前端展示层（frontend/）  Streamlit 多页面                 │
│       纯 HTTP 调用后端，零业务逻辑，全面自定义 CSS 美化         │
├────────────────────────────────────────────────────────────────┤
│  L6  API 接口层（api/）  FastAPI RESTful                       │
│       JWT 鉴权依赖 + 请求日志中间件 + 全局异常处理器 + CORS     │
├────────────────────────────────────────────────────────────────┤
│  L5  业务服务层（services/）  6 大业务模块                      │
│       Auth / KB / Document / Chat / Agent / Audit              │
│       四级权限拦截 + 审计日志统一写入 + 异步任务调度             │
├────────────────────────────────────────────────────────────────┤
│  L4  AI 能力层（ai/）                                          │
│       ├─ ai/rag_engine/        RAG 检索引擎                     │
│       └─ ai/agent_langgraph/   LangGraph 智能 Agent             │
├────────────────────────────────────────────────────────────────┤
│  L3  通用工具 Utils 层（utils/）                               │
│       LLM/嵌入/OCR 客户端 · JWT/密码 · 权限 · 异步任务 · 异常/错误码 │
├────────────────────────────────────────────────────────────────┤
│  L2  配置层（config/）                                          │
│       settings 全局配置单例 + constants 常量枚举 + logging       │
├────────────────────────────────────────────────────────────────┤
│  L1  数据持久层（db/）  三者分离存储                            │
│       PostgreSQL（元数据） + 向量库（Chroma/Milvus） + 文件系统  │
└────────────────────────────────────────────────────────────────┘
```

### L1 数据持久层（db/）

- **职责**：只存业务元数据，严格遵守「三者分离存储」铁则——PostgreSQL 存元数据、向量库存 chunk+embedding、文件系统存原始文档。
- **核心文件**：`models.py`（9 张表 ORM 模型）、`schemas.py`（Pydantic DTO）、`crud/`（7 个 CRUD 类）、`session.py`（同步/异步会话）、`init_db.py`（建表 + 初始化管理员）。
- **依赖**：仅依赖 `config.constants`（枚举），不依赖上层。

### L2 配置层（config/）

- **职责**：集中管理全部配置，杜绝魔法数字/字符串。
- `settings.py`：pydantic-settings 从 `.env`/环境变量加载，单例模式；覆盖数据库、JWT、LLM、嵌入、向量库、BM25、重排、RAG、Agent、异步任务、OCR、文件、日志、CORS 等全部配置项。
- `constants.py`：全部枚举（用户角色、KB 权限、文档状态、审计动作等）。
- `logging_config.py`：多级别日志 + 按天滚动 + 独立审计通道。

### L3 通用工具 Utils 层（utils/）

- **职责**：公共能力统一封装，杜绝各模块重复实现。
- LLM 客户端（OpenAI 兼容协议）、嵌入客户端、OCR 引擎（可选）、安全工具（JWT 双令牌 + bcrypt）、权限校验（四级 RBAC）、异步任务抽象（BackgroundTasks/Celery 切换）、统一异常体系 + 错误码、统一响应封装、文件安全工具、文本工具。

### L4 AI 能力层（ai/）

#### ai/rag_engine/ — RAG 检索引擎

| 子模块 | 职责 |
|--------|------|
| document_parser | PDF（PyMuPDF+OCR 回退）/ DOCX / MD / TXT 解析 |
| chunker | 语义分块（嵌入相似度边界检测）+ 递归分块兜底 |
| vector_store | Chroma / Milvus 二选一封装（工厂切换） |
| bm25_retriever | BM25 关键词召回（jieba 分词，磁盘持久化） |
| reranker | BGE-Rerank 精排（FlagEmbedding 缺失降级词重叠） |
| hybrid_retriever | 多路召回 min-max 归一化加权融合 + 去重 |
| hallucination_detector | 上下文充分性 + 无答案识别 + 支撑度校验 |
| citation_formatter | 引用标注（文档名 + 页码 + 原文片段） |
| doc_version_manager | 版本索引编排（重建/回滚） |
| rag_pipeline | 统一对外入口（ingest / retrieve / answer） |

#### ai/agent_langgraph/ — LangGraph 智能 Agent

| 子模块 | 职责 |
|--------|------|
| agent_config | Agent 配置（重试次数/记忆窗口全配置化） |
| state | 状态图 State（TypedDict） |
| graph_builder | LangGraph 状态图构建 |
| nodes | 规划 / 执行 / 反思 / 响应 四节点 |
| tools | 工具集（内部 RAG 检索 + 外部摘要/CSV） |
| memory | 短期滑动窗口 + 长期偏好记忆（裁剪 + 持久化） |
| agent_manager | 统一执行入口（execute，含审计 + 任务落库） |

### L5 业务服务层（services/）

| 模块 | 职责 |
|------|------|
| auth_service | 注册 / 登录 / JWT 双令牌 / 改密 / 令牌解析 |
| kb_service | 知识库 CRUD + 成员权限管理（四级拦截） |
| document_service | 文档上传 / 异步向量化 / 版本 / 删除 / 重建 |
| chat_service | 会话管理 + RAG 问答 |
| agent_service | Agent 任务编排（复用 AgentManager + agent_tasks 表） |
| audit_service | 审计日志查询（只读） |

统一审计入口 `services.write_audit_log`（文件审计 + DB 审计双写）。

### L6 API 接口层（api/）

- `main.py`：FastAPI 实例 + CORS + 中间件 + 路由 + 异常处理器。
- `deps.py`：JWT 鉴权依赖 `get_current_user`。
- `middleware.py`：请求日志（路径/用户/耗时）。
- `handlers.py`：全局异常处理器（业务异常/校验异常/系统异常 → 统一标准返回体）。
- `router/`：6 个路由（auth / kb / document / chat / agent / audit），RESTful 风格。

### L7 前端展示层（frontend/）

- Streamlit 多页面，纯 HTTP 调用后端，不直接操作数据库/RAG/services。
- `styles.py` 全局自定义 CSS 美化（卡片化、柔和配色、阴影、圆角、hover 动画）。
- 6 大页面：登录注册、知识库、文档、智能问答、Agent 任务、审计日志。

---

## 三、模块间调用依赖关系

```
frontend（Streamlit）
   │  HTTP /api/v1/*（JWT Bearer）
   ▼
api（FastAPI）── 鉴权 → 参数接收 → 调用 service
   │
   ▼
services ──┬── db.crud（数据库操作，不写原生 SQL）
           ├── ai.rag_engine（RagPipeline 统一入口）
           ├── ai.agent_langgraph（AgentManager 统一入口）
           └── utils（异常/错误码/文件安全/权限/异步任务/审计）
```

**依赖铁则**：
- 上层只依赖相邻下层，禁止跨层、禁止反向依赖；
- 数据库操作统一走 `db.crud`；RAG 能力统一走 `rag_pipeline`；Agent 能力统一走 `agent_manager`；审计写操作统一走 `services.write_audit_log`；
- 前端只通过 HTTP 与后端交互，禁止 import 任何后端内部模块。

---

## 四、核心技术点

### 1. BM25 + 向量 + 重排 混合 RAG

多路召回：BM25 关键词召回（jieba 分词）+ 向量语义召回（BGE 嵌入），分别 min-max 归一化后按权重（0.7 向量 + 0.3 BM25）加权融合，按 chunk_id 去重，最后由 BGE-Rerank 精排。语义分块按嵌入相似度边界检测切分，递归分块兜底。生成阶段配合幻觉抑制（上下文充分性 + 无答案识别 + 支撑度校验）与引用溯源，显著降低幻觉、提升召回准确率。

### 2. LangGraph「任务拆解-执行-反思重试」Agent

基于 LangGraph 状态图（StateGraph）构建 `规划 → 执行 → 条件路由 → 反思 → 重新规划` 的闭环。任务失败自动分析原因、修正策略并重试，受 `max_retry` 上限约束防死循环。工具集分内部 RAG 检索与外部业务工具（文档摘要、CSV 导出）两类；配短期滑动窗口 + 长期偏好记忆（条数上限裁剪 + JSON 持久化 + 相似度检索）。

### 3. 四级 RBAC 权限管控

知识库级 `owner > admin > write > read` 四级权限：owner 全权限、admin 管理成员/改配置、write 上传编辑文档、read 只读问答。service 层统一拦截，越权抛 `PermissionException`（错误码 1200003）并写审计（`permission_denied`）。

### 4. 全链路审计日志

所有业务变更操作（登录/注册/建库/改权限/上传/问答/Agent）统一走 `services.write_audit_log`，双写文件审计（`utils.logger.log_audit`）+ 数据库审计（`audit_log_crud`）。审计日志只追加、不修改、不删除。

### 5. 前后端分离架构

FastAPI 提供 RESTful API（统一 `{code, message, data, timestamp}` 返回体 + 全局异常处理），Streamlit 前端纯 HTTP 调用，JWT Bearer 鉴权，CORS 配置化。

### 6. 异步任务处理

大文档向量化通过异步任务抽象层（BackgroundTasks/Celery 可切换）后台执行，上传接口立即返回 task_id，不阻塞 HTTP 请求。

---

## 五、项目亮点总结（可直接摘抄至简历/论文）

> **一句话定位**：设计并实现了一套企业私有知识库智能助手，融合「混合检索增强生成（Hybrid RAG）」与「LangGraph 反思式 Agent」两大 AI 能力，具备完整的分层架构、四级权限管控与全链路审计。

- **多路混合召回 + 重排**：BM25 关键词召回与向量语义召回加权融合，BGE-Rerank 精排，配合语义分块与幻觉抑制，兼顾召回率与准确率。
- **反思式 Agent**：LangGraph 状态图实现「规划-执行-反思重试」闭环，任务失败自动修正策略，支持多工具编排（RAG 检索、文档摘要、CSV 导出）。
- **企业级工程化**：JWT 双令牌鉴权、四级 RBAC 权限隔离、全链路审计日志、统一异常处理、异步任务调度。
- **可插拔设计**：向量库（Chroma/Milvus）、大模型（OpenAI 兼容协议，DeepSeek/Qwen/Ollama）、异步引擎（BackgroundTasks/Celery）均可配置切换。
- **工程质量**：6 层架构严格分层、依赖注入、工厂模式、Fake 注入离线测试（6 套测试脚本）、Docker Compose 一键部署。
- **高颜值前端**：Streamlit 全面自定义 CSS 美化，卡片化布局、聊天气泡、流式打字动画，符合企业级产品质感。

**技术栈关键词**：Python、FastAPI、Streamlit、SQLAlchemy、PostgreSQL、Chroma/Milvus、LangGraph、BGE-Embedding/Rerank、BM25、JWT、Docker。
