# 企业私有知识库智能助手

> 融合高级增强 RAG + LangGraph Agent 智能任务执行的企业级知识库平台
> 面向真实企业内部使用 · 本科毕业设计 · 求职项目展示

---

## 🌟 项目简介

企业私有知识库智能助手是一套面向企业内部的知识库问答与智能任务执行系统。员工可上传 PDF、Word、Markdown、扫描版文档以及图片构建私有知识库，通过自然语言问答获取精准答案（含引用溯源），Agent 可自主拆解任务、调用工具完成文档摘要、CSV 导出等复杂任务。系统具备用户权限隔离（owner/admin/write/read 四级）、完整审计日志、Docker 一键部署等企业级特性，并支持**多模态图片向量化检索**（PDF 内嵌图 + png/jpg 直接上传，图片/文字跨模态召回）。

## 🚀 核心特性

1. **多路混合召回 + BGE 重排**：BM25 关键词召回 + 向量语义召回双路融合（min-max 归一化加权），BGE-Rerank 精排，显著提升召回准确率、降低幻觉
2. **LangGraph 反思式 Agent**：规划 → 执行 → 反思三节点闭环，任务失败自动分析原因并重试（受重试上限约束），绝非简单 prompt 工具调用
3. **语义分块 + 引用溯源**：基于嵌入相似度边界检测的语义分块，回答标注文档名 + 页码 + 原文片段，有据可查
4. **企业级工程化**：JWT 双令牌鉴权 + 知识库四级权限隔离 + 完整审计日志 + Docker Compose 部署
5. **可插拔架构**：向量库（Chroma/Milvus 二选一）、大模型（OpenAI 兼容协议）、异步任务引擎（BackgroundTasks/Celery）均可配置切换
6. **高颜值前端**：Streamlit 全面自定义 CSS 美化，卡片化布局、柔和配色、聊天气泡、流式打字动画
7. **多模态图片检索**：PDF 内嵌图自动提取 + png/jpg 直接上传，OCR 文本通道与 Chinese-CLIP 图片向量通道**双通道**入库，支持「文字描述 → 召回图片」，问答页直接渲染命中图片；`ENABLE_IMAGE_EMBED` 开关一键关闭即退回纯文本 RAG

---

## 🏗️ 系统架构

### 六层分层架构（自上而下）

```
┌──────────────────────────────────────────────────────────────┐
│  第 1 层   UI 表现层（Streamlit 多页面，纯 HTTP 调用后端）     │
│  登录 / 知识库 / 文档 / 智能问答 / Agent任务 / 审计            │
├──────────────────────────────────────────────────────────────┤
│  第 2 层   API 接口层（FastAPI RESTful）                      │
│  JWT 鉴权 + 请求日志中间件 + 全局异常处理 + CORS               │
├──────────────────────────────────────────────────────────────┤
│  第 3 层   业务服务层（Services）                              │
│  Auth / KB / Document / Chat / Agent / Audit                  │
│  四级权限校验 + 审计日志统一写入 + 异步任务调度                 │
├──────────────────────────────────────────────────────────────┤
│  第 4 层   AI 能力层                                          │
│  ┌────────────────────┬─────────────────────────────────┐    │
│  │ RAG 引擎            │ Agent 智能层（LangGraph）        │    │
│  │ • 文档解析 + OCR    │ • 状态图（StateGraph）           │    │
│  │ • 语义分块          │ • 规划→执行→反思闭环             │    │
│  │ • BM25 + 向量召回   │ • 工具：内部RAG + 外部业务        │    │
│  │ • BGE 重排          │ • 短期滑动窗口 + 长期记忆         │    │
│  │ • 图片多模态检索    │                                  │    │
│  │ • 幻觉抑制 + 引用   │                                  │    │
│  └────────────────────┴─────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│  第 5 层   通用工具 Utils 层                                  │
│  配置管理 / LLM 客户端 / 嵌入客户端 / OCR 引擎 / 统一错误码     │
│  安全工具（JWT/bcrypt）/ 权限校验 / 异步任务 / 文件/文本工具    │
├──────────────────────────────────────────────────────────────┤
│  第 6 层   数据持久层（三者分离存储）                          │
│  PostgreSQL（业务元数据）  向量库（Chroma/Milvus 二选一）      │
│  文件系统（原始文档二进制）                                    │
└──────────────────────────────────────────────────────────────┘
```

> 详细架构说明见 [docs/architecture.md](docs/architecture.md)，模块说明见 [docs/module_intro.md](docs/module_intro.md)

### 三者分离存储铁则

| 存储介质 | 存放内容 |
|---------|---------|
| PostgreSQL | 业务元数据（用户 / 知识库 / 文档元信息 / 会话 / Agent 任务 / 审计日志） |
| 向量库（Chroma/Milvus） | chunk 分块文本 + embedding 向量 + BM25 索引；图片向量存独立集合 `kb_{id}_img`（含 image_path / page_number 等元数据） |
| 文件系统 | 原始文档二进制（通过 DB 的 `file_path` 读取）+ 提取出的内嵌图片（上传目录 `kb_{kb_id}/images/`） |

---

## 📁 项目目录结构

```
enterprise-kb-assistant/
├── ai/                      # AI 能力层
│   ├── rag_engine/          #   RAG 引擎（解析/分块/召回/重排/图片检索/幻觉抑制）
│   │   ├── document_parser/ #     文档解析器（PDF/DOCX/MD/TXT/图片）
│   │   └── image_retriever.py  #  图片多模态检索（独立集合 kb_{id}_img）
│   └── agent_langgraph/     #   Agent 智能层（状态图/工具/记忆）
├── api/                     # API 接口层（FastAPI）
│   ├── main.py              #   主入口（中间件/路由/异常处理）
│   ├── deps.py              #   JWT 鉴权依赖
│   ├── middleware.py        #   请求日志中间件
│   ├── handlers.py          #   全局异常处理器
│   └── router/              #   6 个路由（auth/kb/document/chat/agent/audit）
├── services/                # 业务服务层（6 个 service）
├── db/                      # 数据持久层
│   ├── models.py            #   ORM 模型
│   ├── schemas.py           #   Pydantic DTO
│   ├── crud/                #   数据访问层
│   ├── session.py           #   会话管理
│   └── init_db.py           #   数据库初始化（建表 + 管理员）
├── utils/                   # 通用工具层
│   ├── multimodal_embedding_client.py  #  多模态嵌入客户端（Chinese-CLIP）
├── config/                  # 配置层（settings + constants + logging）
├── frontend/                # UI 表现层（Streamlit）
│   ├── app.py               #   主入口
│   ├── pages/               #   6 大页面
│   ├── styles.py            #   全局自定义 CSS
│   ├── api_client.py        #   HTTP 请求封装
│   └── Dockerfile           #   前端镜像
├── tests/                   # 分步骤测试（test_step1 ~ test_step6）
├── docs/                    # 毕设文档（架构/模块/实验/部署）
├── Dockerfile               # 后端镜像
├── docker-compose.yml       # 一键编排（PG + 后端 + 前端）
├── requirements.txt         # 依赖清单（精确锁定版本）
├── .env.example             # 环境变量模板
└── .gitignore
```

---

## 🔧 技术栈

| 层级 | 技术选型 | 版本 |
|------|---------|------|
| 前端 | Streamlit | 1.61.1 |
| 后端 | FastAPI + Starlette + Uvicorn | 0.141.1 / 1.3.1 / 0.34.0 |
| 数据库 | PostgreSQL（生产）/ SQLite（开发） | 16 / — |
| ORM | SQLAlchemy | 2.0.36 |
| 向量库 | Chroma / Milvus（二选一） | 0.5.23 / 2.4.x |
| AI 框架 | LangGraph | 1.0.7 |
| LLM | OpenAI 兼容协议（DeepSeek / Qwen / Ollama） | — |
| 嵌入模型 | BGE-Embedding（sentence-transformers） | 3.3.1 |
| 多模态模型 | Chinese-CLIP（transformers，本地，图片向量化） | — |
| 重排模型 | BGE-Rerank（FlagEmbedding，可降级词重叠） | — |
| OCR | PaddleOCR（可选） | 3.2.0 |
| 异步任务 | BackgroundTasks / Celery + Redis（可选） | — |
| 鉴权 | JWT 双令牌 + bcrypt | PyJWT 2.13.0 |
| 部署 | Docker Compose | — |

---

## 💻 硬件与模型接口说明

### 大模型接口（OpenAI 兼容协议）

系统通过 OpenAI 兼容的 `/v1/chat/completions` 接口调用大模型，可无缝切换任意兼容提供商。已适配：

| 提供商 | Base URL | 模型示例 |
|-------|----------|---------|
| DeepSeek | `https://api.deepseek.com` | `deepseek-v4-flash` / `deepseek-v4-pro` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| 阿里 Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| Ollama（本地） | `http://localhost:11434/v1` | `qwen2.5:7b` |

> ⚠️ **实测结论**：DeepSeek 官方 API 仅提供**对话模型**（`deepseek-v4-flash` / `deepseek-v4-pro`），不提供 embedding、rerank、多模态（vision）接口。因此本项目的嵌入、重排、图片向量化均使用**本地模型**（BGE / BGE-Rerank / Chinese-CLIP），仅 LLM 对话走 DeepSeek。

切换方式：修改 `.env` 中的 `LLM_PROVIDER / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`。

### 硬件建议

- **CPU 模式**：8GB+ 内存（BGE 嵌入 + 重排模型运行于 CPU）；启用图片向量化后，Chinese-CLIP（约 753MB）额外占用约 1.5GB 内存，建议 **16GB+**
- **GPU 模式**（推荐）：4GB+ 显存（`sentence-transformers` / `FlagEmbedding` / `transformers` 自动使用 CUDA）

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Docker & Docker Compose（推荐部署方式）

### 方式一：本地手动部署

```bash
# 1. 创建虚拟环境
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. 安装依赖（核心运行依赖；启用 Milvus/OCR/BGE-rerank 需取消注释对应行）
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env              # Windows: copy .env.example .env
# 编辑 .env：填入 LLM_API_KEY、按需调整数据库/向量库

# 4. 初始化数据库（建表 + 创建默认管理员，复用 db/init_db.py）
python -m db.init_db

# 5. 启动后端（另开终端）
python -X utf8 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 6. 启动前端（另开终端）
streamlit run frontend/app.py
```

### 方式二：Docker Compose 一键部署

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env：填 LLM_API_KEY；数据库默认走容器内 PostgreSQL

# 2. 一键启动（自动编排 PostgreSQL + 后端 + 前端，pg 优先启动）
docker-compose up -d --build

# 3. 查看运行状态
docker-compose ps

# 4. 访问
#   前端:      http://localhost:8501
#   后端 API:  http://localhost:8000
#   API 文档:  http://localhost:8000/docs
```

### 🎬 快速演示账号

> 首次启动由 `db/init_db.py` 自动创建，可直接用于快速上手演示与答辩展示。

| 账号 | 密码 | 角色 | 说明 |
|------|------|------|------|
| `admin` | `admin123456` | 系统管理员（admin） | 全局管理，可创建知识库并拥有 owner 全权限 |
| `demo` | `demo123456` | 普通用户（normal） | 演示用户，可用于测试权限隔离（需被 owner 添加为成员） |

**演示建议**：
1. 用 `admin` 登录 → 创建知识库 → 上传文档 → 问答 → 提交 Agent 任务（体验完整 owner 权限）；
2. 用 `demo` 登录 → 尝试访问 admin 的知识库（体验 read 权限隔离与越权拦截提示）。

> ⚠️ 生产环境请**立即修改默认密码**（登录后右上角「修改密码」），或删除默认账号。

---

## ⚙️ 关键配置说明

### 大模型切换（OpenAI 兼容）

```bash
# DeepSeek（推荐，deepseek-v4-flash / deepseek-v4-pro）
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-xxx
LLM_MODEL=deepseek-v4-flash
```

### 向量库切换

```bash
# 本地开发（轻量，容器内本地持久化，无需额外服务）
VECTOR_STORE_TYPE=chroma

# 生产部署（连接外部 Milvus 服务）
VECTOR_STORE_TYPE=milvus
MILVUS_HOST=localhost
MILVUS_PORT=19530
```

### 异步任务引擎切换

```bash
# 开发（线程后台，默认）
ASYNC_TASK_ENGINE=background

# 生产（分布式）
ASYNC_TASK_ENGINE=celery
CELERY_BROKER_URL=redis://localhost:6379/0
```

### 多模态图片向量化开关

```bash
# 开启图片向量化（默认关闭，关闭即退回纯文本 RAG，不加载多模态模型）
ENABLE_IMAGE_EMBED=true
MULTIMODAL_EMBEDDING_MODEL=OFA-Sys/chinese-clip-vit-base-patch16
MULTIMODAL_EMBEDDING_DEVICE=cpu       # cpu / cuda
IMAGE_MAX_SIDE=1024                   # 大图预处理压缩最大边长
IMAGE_VECTOR_TOP_K=5                  # 图片向量召回条数
```

> ⚠️ 首次启用需下载 Chinese-CLIP 模型（约 753MB）。国内网络建议先设置镜像下载：
> ```bash
> HF_ENDPOINT=https://hf-mirror.com python -c "from huggingface_hub import snapshot_download; snapshot_download('OFA-Sys/chinese-clip-vit-base-patch16')"
> ```
> 下载后本地启动后端时加 `HF_HUB_OFFLINE=1` 即可离线加载（无需每次联网）。

---

## 🧪 测试验证方法

项目按 6 个开发步骤配套 6 个测试脚本，覆盖各层核心能力，全部离线可跑（注入 Fake 组件，不依赖真实模型/向量库）：

```bash
python tests/test_step1_utils.py     # Utils 工具层
python tests/test_step2_db.py        # 数据库层（ORM/CRUD）
python tests/test_step3_rag.py       # RAG 引擎（解析/分块/召回/重排/幻觉抑制）
python tests/test_step4_agent.py     # Agent 智能层（状态图/工具/记忆/反思重试）
python tests/test_step5_services.py  # 业务服务层（鉴权/权限隔离/上传/问答/审计）
python tests/test_step6_api.py       # API 接口层（鉴权/权限/异常格式）
```

---

## 🧭 运行演示

1. **注册登录**：访问前端，注册账号并登录
2. **创建知识库**：知识库管理页创建，可添加成员并设置权限
3. **上传文档**：文档管理页上传 PDF/Word/MD，实时查看向量化进度（`解析中 → 提取图片中 → 文本向量化中 → 图片向量化中 → 就绪`）
4. **上传图片**：文档管理页上传 png/jpg，走 OCR 文本 + 图片向量双通道入库
5. **智能问答**：问答页选择知识库提问，查看带引用的答案；命中图片时引用下方直接渲染图片
6. **Agent 任务**：Agent 页提交任务，观察规划→执行→反思的执行轨迹

---

## 📊 实验与效果评估

实验设计指南详见 [docs/experiment_guide.md](docs/experiment_guide.md)，包含：召回准确率对比（BM25 vs 向量 vs 混合+重排）、分块策略对比、幻觉率评估、Agent 任务成功率与重试效果、并发 QPS 压测。

## 📝 毕业设计文档

- [系统架构设计说明](docs/architecture.md) — 论文《系统架构设计》章节
- [模块详细说明](docs/module_intro.md) — 论文《系统设计与实现》章节
- [实验设计指南](docs/experiment_guide.md) — 论文《实验与分析》章节
- [部署测试说明](docs/deploy.md) — 部署与连通性验证

---

## 📄 License

MIT License
