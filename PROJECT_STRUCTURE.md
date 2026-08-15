# 企业私有知识库智能助手平台 — 项目目录树（修正版）

```
enterprise-kb-assistant/
├── README.md                          # 项目主文档（介绍、部署、运行、实验指南）
├── requirements.txt                   # Python 依赖（带版本号）
├── docker-compose.yml                 # Docker Compose 一键部署
├── .env.example                       # 环境变量模板
├── .gitignore
│
├── config/                            # ========== 配置层（已并入 utils 逻辑层）==========
│   ├── __init__.py
│   ├── settings.py                    # 全局配置（读取 .env，单例模式，向量库开关）
│   ├── logging_config.py              # 日志配置（多级别、滚动、审计日志）
│   └── constants.py                   # 常量定义（枚举、状态码、角色、任务状态）
│
├── utils/                             # ========== 第5层 · 通用工具 Utils 层 ==========
│   ├── __init__.py
│   ├── config_loader.py               # 配置加载与热更新（封装 settings）
│   ├── llm_client.py                  # LLM 客户端封装（OpenAI 兼容，可切换 DeepSeek/Qwen）
│   ├── embedding_client.py            # 嵌入模型客户端（BGE / OpenAI 兼容）
│   ├── ocr_engine.py                  # OCR 工具引擎（PaddleOCR / Tesseract 封装）
│   ├── error_codes.py                 # 统一错误码定义（业务错误码 + HTTP 映射）
│   ├── exceptions.py                  # 自定义异常类（业务异常、鉴权异常、RAG 异常等）
│   ├── response.py                    # 统一响应封装（success / fail / error）
│   ├── security.py                    # 安全工具（密码哈希 bcrypt、JWT 签发校验）
│   ├── file_utils.py                  # 文件处理工具（格式检测、路径安全、大小校验）
│   ├── text_utils.py                  # 文本处理（中文分词、清洗、归一化）
│   ├── permission.py                  # 权限校验装饰器/工具函数
│   ├── async_task.py                  # 异步任务封装（BackgroundTasks / Celery 可切换）
│   └── logger.py                      # 统一日志器获取
│
├── db/                                # ========== 第6层 · 数据持久层（关系型）==========
│   ├── __init__.py
│   ├── models.py                      # SQLAlchemy ORM 模型
│   │                                  # （User / KnowledgeBase / KBUser / Document /
│   │                                  #  DocumentVersion / Conversation / Message /
│   │                                  #  AgentTask / AuditLog / RequestLog）
│   ├── schemas.py                     # Pydantic Schema（请求/响应 DTO，参数校验）
│   ├── session.py                     # 数据库会话管理（连接池、事务、依赖注入）
│   ├── crud/                          # 数据访问层（CRUD 封装，业务层只通过 crud 操作 DB）
│   │   ├── __init__.py
│   │   ├── user_crud.py
│   │   ├── kb_crud.py                 # 知识库 + 权限
│   │   ├── document_crud.py           # 文档 + 版本
│   │   ├── conversation_crud.py       # 会话 + 消息
│   │   ├── agent_task_crud.py         # Agent 任务执行日志
│   │   └── audit_log_crud.py          # 请求日志 + 审计日志
│   └── migrations/                    # Alembic 数据库迁移脚本
│       └── env.py
│
├── ai/                                # ========== 第4层 · AI 能力层 ==========
│   ├── __init__.py
│   │
│   ├── rag_engine/                    # ----- RAG 子模块 -----
│   │   ├── __init__.py
│   │   ├── document_parser/           # 文档解析
│   │   │   ├── __init__.py
│   │   │   ├── base_parser.py         # 解析器抽象基类
│   │   │   ├── pdf_parser.py          # PDF 解析（PyMuPDF + OCR 回退）
│   │   │   ├── docx_parser.py         # Word 解析
│   │   │   └── md_parser.py           # Markdown 解析
│   │   ├── chunker/                   # 文档分块
│   │   │   ├── __init__.py
│   │   │   ├── base_chunker.py
│   │   │   ├── semantic_chunker.py    # 语义分块（基于嵌入相似度的边界检测）
│   │   │   └── recursive_chunker.py   # 递归字符分块（兜底策略）
│   │   ├── vector_store/              # 向量数据库（配置二选一）
│   │   │   ├── __init__.py
│   │   │   ├── base_store.py          # 向量库抽象基类（统一接口）
│   │   │   ├── chroma_store.py        # Chroma 实现（开发/轻量部署）
│   │   │   ├── milvus_store.py        # Milvus 实现（生产/企业级）
│   │   │   └── store_factory.py       # 向量库工厂（根据配置创建实例）
│   │   ├── bm25_retriever/            # BM25 关键词召回
│   │   │   ├── __init__.py
│   │   │   └── bm25_engine.py         # BM25Okapi + jieba 中文分词
│   │   ├── reranker/                  # 重排模块
│   │   │   ├── __init__.py
│   │   │   └── bge_reranker.py        # BGE-Rerank 模型（FlagEmbedding）
│   │   ├── hybrid_retriever.py        # 混合召回主入口（BM25 + 向量 → 融合 → 重排）
│   │   ├── hallucination_detector.py  # 幻觉抑制（引用一致性校验 + 无答案检测）
│   │   ├── citation_formatter.py      # 引用来源标注（文档名 + 页码 + 原文片段）
│   │   ├── doc_version_manager.py     # 文档版本管理（增量更新、版本回滚）
│   │   └── rag_pipeline.py            # RAG 流水线总控（问答主入口）
│   │
│   └── agent_langgraph/               # ----- Agent 子模块 -----
│       ├── __init__.py
│       ├── graph_builder.py           # LangGraph 状态图构建（规划→执行→反思循环）
│       ├── state.py                   # Agent 状态定义（TypedDict / Pydantic）
│       ├── nodes/                     # 图节点实现
│       │   ├── __init__.py
│       │   ├── planner_node.py        # 任务拆解与规划节点（生成子任务+工具选择）
│       │   ├── executor_node.py       # 工具执行节点（调度具体工具）
│       │   ├── reflector_node.py      # 反思节点（结果校验、错误分析、重试规划）
│       │   └── responder_node.py      # 最终汇总响应节点
│       ├── tools/                     # 工具集（分两类）
│       │   ├── __init__.py
│       │   ├── base_tool.py           # 工具基类（统一接口 + 元数据）
│       │   ├── internal/              # 【内部 RAG 检索工具】
│       │   │   ├── __init__.py
│       │   │   └── kb_search_tool.py  # 知识库搜索工具（调用 RAG pipeline）
│       │   └── external/              # 【外部业务工具】
│       │       ├── __init__.py
│       │       ├── doc_summary_tool.py    # 文档摘要工具
│       │       ├── export_csv_tool.py     # 导出 CSV 工具
│       │       ├── weekly_report_tool.py  # 周报生成工具
│       │       └── history_query_tool.py  # 会话历史查询工具
│       ├── memory/                    # 记忆模块
│       │   ├── __init__.py
│       │   ├── short_term_memory.py   # 短期会话记忆（滑动窗口 + 滚动摘要）
│       │   └── long_term_memory.py    # 用户长期业务记忆（向量存储 + 关键词索引）
│       └── agent_manager.py           # Agent 管理器（模式识别、图启动、状态跟踪）
│
├── services/                          # ========== 第3层 · 业务服务层 ==========
│   ├── __init__.py
│   ├── auth_service.py                # 认证服务（注册、登录、刷新令牌）
│   ├── kb_service.py                  # 知识库服务（CRUD + 权限管理）
│   ├── document_service.py            # 文档服务（上传触发异步解析 + 向量化）
│   ├── chat_service.py                # 问答服务（普通 RAG 模式）
│   ├── agent_service.py               # Agent 服务（任务模式 + 执行日志）
│   ├── audit_service.py               # 审计服务（日志记录与查询）
│   └── task_scheduler.py              # 异步任务调度（大文档向量化、批量处理）
│
├── api/                               # ========== 第2层 · API 接口层 ==========
│   ├── __init__.py
│   ├── app.py                         # FastAPI 应用入口（中间件、路由注册、启动事件）
│   ├── dependencies.py                # FastAPI 依赖（鉴权依赖、DB 会话、当前用户）
│   ├── middleware/                    # 中间件
│   │   ├── __init__.py
│   │   ├── request_log_middleware.py  # 请求日志中间件（记录所有 HTTP 请求）
│   │   └── error_handler.py           # 全局异常处理（统一错误响应格式）
│   └── v1/                            # API v1 版本（路由按业务域拆分）
│       ├── __init__.py
│       ├── auth_router.py             # /auth/*  注册/登录/刷新/用户信息
│       ├── kb_router.py               # /kb/*    知识库 CRUD + 权限管理
│       ├── document_router.py         # /doc/*   文档上传/列表/删除/版本（异步）
│       ├── chat_router.py             # /chat/*  问答对话（普通 RAG 模式，支持流式）
│       ├── agent_router.py            # /agent/* Agent 任务执行（任务模式）
│       ├── conversation_router.py     # /conv/*  会话管理（列表/详情/删除）
│       └── log_router.py              # /log/*   审计日志查询（管理端）
│
├── ui/                                # ========== 第1层 · UI 表现层 ==========
│   ├── __init__.py
│   ├── app.py                         # Streamlit 主入口（页面路由 + 鉴权守卫）
│   ├── pages/                         # 多页面（按 Streamlit Pages 规范）
│   │   ├── 01_🔐_登录.py
│   │   ├── 02_📚_知识库管理.py
│   │   ├── 03_📄_文档管理.py
│   │   ├── 04_💬_智能问答.py
│   │   ├── 05_🤖_Agent任务.py
│   │   └── 06_📊_日志审计.py
│   ├── components/                    # 可复用 UI 组件
│   │   ├── __init__.py
│   │   ├── sidebar.py                 # 侧边栏（导航 + 用户信息）
│   │   ├── chat_bubble.py             # 对话气泡组件
│   │   └── file_uploader.py           # 文件上传组件（带进度）
│   └── utils/
│       ├── __init__.py
│       ├── api_client.py              # 后端 API 客户端（requests 封装）
│       └── session_state.py           # Streamlit 会话状态管理
│
├── worker/                            # ========== 异步任务 Worker（可选独立部署）==========
│   ├── __init__.py
│   ├── tasks.py                       # Celery 任务定义（文档解析、向量化、重建索引）
│   └── celery_app.py                  # Celery 应用配置
│
├── tests/                             # ========== 测试 ==========
│   ├── __init__.py
│   ├── unit/
│   │   ├── test_rag_pipeline.py
│   │   ├── test_hybrid_retriever.py
│   │   ├── test_bm25.py
│   │   ├── test_reranker.py
│   │   ├── test_agent_graph.py
│   │   ├── test_auth.py
│   │   └── test_permission.py
│   ├── integration/
│   │   └── test_api_flow.py
│   └── conftest.py
│
├── data/                              # ========== 运行时数据目录 ==========
│   ├── uploads/                       # 原始文档存储（按知识库/用户分目录）
│   ├── vector_store/                  # 向量库持久化（Chroma 模式下）
│   ├── bm25_index/                    # BM25 索引文件（按知识库独立）
│   ├── long_term_memory/              # 用户长期记忆向量存储
│   └── exports/                       # 导出文件目录（CSV 等）
│
├── docker/                            # ========== Docker 构建 ==========
│   ├── backend.Dockerfile             # 后端服务镜像
│   ├── frontend.Dockerfile            # Streamlit 前端镜像
│   ├── worker.Dockerfile              # Celery Worker 镜像（可选）
│   └── entrypoint.sh
│
└── docs/                              # ========== 文档 ==========
    ├── architecture.md                # 系统架构说明（毕设用）
    ├── module_intro.md                # 模块详细说明（毕设用）
    ├── experiment_guide.md            # 实验设计与效果对比（毕设用）
    └── api_docs.md                    # API 文档补充
```
