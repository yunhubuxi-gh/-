# 课程试卷智能命题校验批改系统

> 基于增强 RAG + LangGraph 双 Agent 的高校课程智能命题、试卷校验与溯源批改平台
> 面向高校教师 / 学生 · 本科毕业设计 · 求职项目展示

---

## 🌟 项目简介

课程试卷智能命题校验批改系统，在「企业私有知识库」底座之上，面向高校课程场景构建完整的 **命题 → 校验 → 答题 → 批改** 闭环：

- **教师侧**：上传课程讲义 / 课件（PDF、Word、Markdown、扫描版、图片）构建课程库，一键生成试卷 —— 命题 Agent 依据课件知识库出题，校验评审 Agent 逐题核验（知识点是否真实存在 / 答案是否正确 / 是否超纲 / 是否歧义），不合格题自动回传重生成；
- **学生侧**：在线作答，客观题由规则自动判分（不调用大模型），主观题由 RAG 检索课件原文 + 大模型**溯源批改**（得分 + 优缺点 + 课件原文引用）；
- **知识问答**：基于 BM25 + 向量 + 重排的混合检索增强生成，答案附带文档名 / 页码 / 原文片段引用；
- **多模态检索**：支持「文字描述 → 召回图片」，PDF 内嵌图与 png/jpg 直接上传，OCR 文本通道与 Chinese-CLIP 图片向量通道**双通道**入库，问答页直接渲染命中图片。

系统具备用户权限隔离（owner/admin/write/read 四级）、完整审计日志、后台异步任务、Docker 一键部署等企业级特性，底层 RAG / Agent / OCR / 多模态全部**进程内本地推理**，无外部依赖。

---

## 🚀 核心特性

1. **双 Agent 智能命题（LangGraph）**：命题 Agent → 校验评审 Agent 两个独立节点串联，逐题 RAG 检索课件原文校验，不合格题自动回传重生成（受 `EXAM_MAX_ITERATE` 上限约束），完整执行轨迹（检索了什么 → 出了什么题 → 逐题校验 → 重生成）可逐轮展开
2. **知识库溯源批改**：客观题规则判分（选择题精确匹配、填空题关键词匹配），主观题 RAG 检索课件原文 + LLM 判分，每题附课件原文引用，杜绝「大模型凭空判分」
3. **多路混合召回 + BGE 重排**：BM25 关键词召回 + 向量语义召回双路融合（min-max 归一化加权），BGE-Rerank 精排，显著提升召回准确率、降低幻觉
4. **图片多模态检索（Chinese-CLIP）**：PDF 内嵌图自动提取 + png/jpg 直接上传，OCR 文本 + CLIP 图片向量双通道入库，支持「文字描述 → 召回图片」；`ENABLE_IMAGE_EMBED` 开关一键关闭即退回纯文本 RAG
5. **语义分块 + 引用溯源**：基于嵌入相似度边界检测的语义分块，回答标注文档名 + 页码 + 原文片段，有据可查
6. **企业级工程化**：JWT 双令牌鉴权 + 知识库四级权限隔离 + 完整审计日志 + 后台异步任务 + Docker Compose 部署
7. **可插拔架构**：向量库（Chroma/Milvus 二选一）、大模型（OpenAI 兼容协议）、异步任务引擎（BackgroundTasks/Celery）均可配置切换
8. **高颜值前端**：Streamlit 全面自定义 CSS 美化，卡片化布局、柔和配色、聊天气泡、流式打字动画、双 Agent 执行轨迹可视化

---

## 🏗️ 系统架构

### 六层分层架构（自上而下）

```
┌──────────────────────────────────────────────────────────────┐
│  第 1 层   UI 表现层（Streamlit 多页面，纯 HTTP 调用后端）     │
│  课程库 / 课件管理 / 试卷中心 / 智能问答 / Agent任务 / 审计     │
├──────────────────────────────────────────────────────────────┤
│  第 2 层   API 接口层（FastAPI RESTful）                      │
│  JWT 鉴权 + 请求日志中间件 + 全局异常处理 + CORS               │
├──────────────────────────────────────────────────────────────┤
│  第 3 层   业务服务层（Services）                              │
│  Auth / KB / Document / Exam / Chat / Agent / Audit           │
│  四级权限校验 + 审计日志统一写入 + 异步任务调度                 │
├──────────────────────────────────────────────────────────────┤
│  第 4 层   AI 能力层                                          │
│  ┌──────────────────────────┬───────────────────────────┐    │
│  │ RAG 引擎                  │ Agent 智能层（LangGraph）  │    │
│  │ • 文档解析 + OCR          │ • 双 Agent 命题-校验闭环   │    │
│  │ • 语义分块                │ • 规划→执行→反思闭环       │    │
│  │ • BM25 + 向量召回         │ • 主观题溯源批改           │    │
│  │ • BGE 重排                │ • 工具：内部RAG + 外部业务  │    │
│  │ • 图片多模态检索          │ • 短期滑动窗口 + 长期记忆   │    │
│  │ • 幻觉抑制 + 引用         │                           │    │
│  └──────────────────────────┴───────────────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│  第 5 层   通用工具 Utils 层                                  │
│  配置管理 / LLM 客户端 / 嵌入客户端 / 多模态客户端 / OCR 引擎   │
│  安全工具（JWT/bcrypt）/ 权限校验 / 异步任务 / 文件/文本工具    │
├──────────────────────────────────────────────────────────────┤
│  第 6 层   数据持久层（三者分离存储）                          │
│  PostgreSQL（业务元数据）  向量库（Chroma/Milvus 二选一）      │
│  文件系统（原始文档 / 课件 / 提取图片）                        │
└──────────────────────────────────────────────────────────────┘
```

### 三者分离存储铁则

| 存储介质 | 存放内容 |
|---------|---------|
| PostgreSQL | 业务元数据（用户 / 课程库 / 课件 / 试卷 / 答卷 / 会话 / Agent 任务 / 审计日志） |
| 向量库（Chroma/Milvus） | chunk 分块文本 + embedding 向量 + BM25 索引；图片向量存独立集合 `kb_{id}_img`（含 image_path / page_number 等元数据，**不存图片二进制**） |
| 文件系统 | 原始课件二进制（通过 DB 的 `file_path` 读取）+ 提取出的内嵌图片（上传目录 `kb_{kb_id}/images/`） |

---

## 🔄 核心业务流程

### 出卷流程（双 Agent 闭环）

```
教师选择课程库 + 题型/数量 + 难度
        │
        ▼
┌─────────────────────┐     ┌──────────────────────────┐
│  命题 Agent          │     │  校验评审 Agent           │
│ ① 按题型多路 RAG 检索 │────▶│  逐题 RAG 检索 + LLM 校验  │
│ ② LLM 出题(题+答案+  │     │  ① 知识点是否真实存在      │
│   知识点+来源引用)    │     │  ② 参考答案是否正确        │
│ ③ 迭代时仅重生成      │◀────│  ③ 是否超纲              │
│   不合格题            │     │  ④ 是否歧义              │
└─────────────────────┘     └──────────────────────────┘
        │                               │
        │  有不合格题 且 未达上限 → 回传重生成
        │  全部通过 / 达上限 → 完成
        ▼
   试卷就绪（含完整执行轨迹）
```

### 答题批改流程

```
学生在线作答 → 客观题规则判分（不调 LLM）
            → 主观题后台溯源批改（RAG 检索课件原文 + LLM 判分）
            → 教师查看批改详情（得分 + 优缺点 + 课件原文引用）
```

---

## 📁 项目目录结构

```
enterprise-kb-assistant/
├── ai/                      # AI 能力层
│   ├── rag_engine/          #   RAG 引擎（解析/分块/召回/重排/图片检索/幻觉抑制）
│   │   ├── document_parser/ #     文档解析器（PDF/DOCX/MD/TXT/图片 + OCR 回退）
│   │   ├── image_preprocess.py  #  图片预处理（过滤极小图/等比例缩放，仅 PIL）
│   │   └── image_retriever.py   #  图片多模态检索（独立集合 kb_{id}_img）
│   └── agent_langgraph/     #   Agent 智能层
│       ├── exam/            #     双 Agent 命题-校验-重生成 + 主观题批改
│       └── ...              #     规划→执行→反思通用 Agent + 工具 + 记忆
├── api/                     # API 接口层（FastAPI）
│   ├── main.py              #   主入口（中间件/路由/异常处理）
│   ├── deps.py              #   JWT 鉴权依赖
│   └── router/              #   7 个路由（auth/kb/document/exam/chat/agent/audit）
├── services/                # 业务服务层（含 exam_service 出卷/批改）
├── db/                      # 数据持久层
│   ├── models.py            #   ORM 模型（含 ExamPaper / AnswerSheet）
│   ├── schemas.py           #   Pydantic DTO
│   ├── crud/                #   数据访问层（含 exam_crud）
│   ├── session.py           #   会话管理
│   └── init_db.py           #   数据库初始化（建表 + 管理员）
├── utils/                   # 通用工具层
│   ├── multimodal_embedding_client.py  # 多模态嵌入客户端（Chinese-CLIP，懒加载）
│   ├── clip_model_loader.py            # modelscope→HF 权重转换（进程内本地推理）
│   └── ...
├── config/                  # 配置层（settings + constants + logging）
├── frontend/                # UI 表现层（Streamlit）
│   ├── app.py               #   主入口（课程库/课件/试卷/问答/Agent/审计）
│   ├── pages/               #   6 大页面
│   ├── styles.py            #   全局自定义 CSS
│   ├── api_client.py        #   HTTP 请求封装
│   └── Dockerfile           #   前端镜像
├── scripts/                 # 迁移脚本（补列 + 建新表，幂等）
├── tests/                   # 分步骤测试（test_step1 ~ test_step6）
├── docs/                    # 毕设文档（架构/模块/实验/部署）
├── Dockerfile               # 后端镜像
├── docker-compose.yml       # 一键编排（PG + 后端 + 前端）
├── requirements.txt         # 依赖清单（精确锁定版本，可选依赖注释化）
├── MODIFY_LIST.md           # 改造修改清单（含图片多模态章节）
├── TEST_IMAGE_GUIDE.md      # 图片多模态测试指南（4 个用例）
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
| 重排模型 | BGE-Rerank（FlagEmbedding，可降级词重叠） | — |
| 多模态模型 | Chinese-CLIP（modelscope，本地，图片向量化） | large-patch14-336px |
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
>
> DeepSeek 为**推理模型**：出题 / 校验 / 批改 / query 改写等调用均显式传入较大 `max_tokens`（默认 2048~4096）+ `temperature=0` + 超时，否则 reasoning 会吃光 token 导致 `content` 为空。

切换方式：修改 `.env` 中的 `LLM_PROVIDER / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`。

### 硬件建议

- **CPU 模式**：8GB+ 内存（BGE 嵌入 + 重排模型运行于 CPU）；启用图片向量化后，Chinese-CLIP（约 1.6GB）额外占用约 1.5~2GB 内存，建议 **16GB+**
- **GPU 模式**（推荐）：4GB+ 显存（`sentence-transformers` / `FlagEmbedding` / `transformers` 自动使用 CUDA；Chinese-CLIP 通过 `CLIP_DEVICE` 自动检测）

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

# 2. 安装依赖（核心运行依赖；启用 Milvus/OCR/BGE-rerank/图片向量化 需取消注释对应行）
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env              # Windows: copy .env.example .env
# 编辑 .env：填入 LLM_API_KEY、按需调整数据库/向量库/图片向量化开关

# 4. 初始化数据库（建表 + 创建默认管理员，复用 db/init_db.py）
python -m db.init_db

# 5. 执行迁移（补 tags / processing_warning 列 + 建试卷/答卷表，幂等）
python -X utf8 scripts/migrate_course.py

# 6. 启动后端（另开终端）
python -X utf8 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 7. 启动前端（另开终端）
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
| `admin` | `admin123456` | 系统管理员（admin） | 全局管理，可创建课程库并拥有 owner 全权限 |
| `demo` | `demo123456` | 普通用户（normal） | 演示用户，可用于测试权限隔离（需被 owner 添加为成员） |

**演示建议**：
1. 用 `admin` 登录 → 创建课程库 → 上传课件（PDF/Word/MD）→ 智能问答 → 生成试卷（体验完整出卷链路）；
2. 试卷就绪后，用 `demo` 账号（被添加为 read 成员）在线作答，观察客观题规则判分 + 主观题溯源批改；
3. 上传图片或含图 PDF（开启 `ENABLE_IMAGE_EMBED=true`），用文字描述提问召回图片。

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

### 双 Agent 命题 / 校验（试卷）

```bash
EXAM_MAX_ITERATE=3            # 双 Agent 最大迭代次数（防死循环）
EXAM_LLM_TIMEOUT=120          # 出题/校验 LLM 超时（秒）
EXAM_LLM_MAX_TOKENS=4096      # 出题/校验 LLM 最大输出（DeepSeek 推理模型需大值）
EXAM_RAG_TOP_K=6              # 出题/校验 RAG 召回课件原文条数
EXAM_TEMPERATURE=0.0          # 出题/校验温度（0=稳定）
```

### 图片多模态向量化开关（Chinese-CLIP）

```bash
# 开启图片向量化（默认关闭，关闭即退回纯文本 RAG，不加载多模态模型）
ENABLE_IMAGE_EMBED=true
CLIP_MODEL_NAME=damo/multi-modal_clip-vit-large-patch14_336_zh   # modelscope 模型 id 或本地 HF 目录
CLIP_DEVICE=auto               # auto/cuda/cpu；auto 优先 cuda，无 GPU 自动降级 cpu
CLIP_MAX_IMAGE_SIDE=336        # 图片预处理最大边长（等比例缩放，防 CLIP 推理 OOM）
CLIP_MIN_IMAGE_SIDE=32         # 图片预处理最小边长，低于此值的极小无效图直接过滤
CLIP_DOWNLOAD_RETRY=3          # 模型下载重试次数，全部失败则关闭图片向量化（文本业务不受影响）
IMAGE_VECTOR_TOP_K=5           # 图片向量召回条数
```

> 📦 **懒加载 + 本地推理**：CLIP 模型**不是服务启动就加载**，而是第一次真正处理图片时才从 modelscope 下载（约 1.6GB）并加载；下载/加载失败会自动关闭图片向量化、日志告警，系统继续跑文本业务，绝不导致服务崩溃。关闭 `ENABLE_IMAGE_EMBED=false` 时不导入 torch/transformers/modelscope，缺依赖也能正常启动。
>
> 图片向量化依赖为**可选**（requirements.txt 中默认注释），需启用时取消注释 `torch / transformers / modelscope / pillow` 后重装即可。

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

图片多模态功能的专项测试见 [TEST_IMAGE_GUIDE.md](TEST_IMAGE_GUIDE.md)（含图 PDF 子状态与部分损坏降级、jpg 召回、开关回退、模型下载失败降级 4 个用例）。

---

## 🧭 运行演示

1. **注册登录**：访问前端，注册账号并登录
2. **创建课程库**：课程库管理页创建，可添加成员并设置权限（owner/admin/write/read）
3. **上传课件**：课件管理页上传 PDF/Word/MD，实时查看向量化进度（`解析文件 → 提取页面图片 → OCR 文字识别 → 文本向量化 → 图片预处理 → 图片向量化 → 就绪`）
4. **上传图片**：课件管理页上传 png/jpg，走 OCR 文本 + 图片向量双通道入库
5. **智能问答**：问答页选择课程库提问，查看带引用的答案；命中图片时引用下方直接渲染图片
6. **生成试卷**：试卷中心选择课程库 + 题型/难度 → 双 Agent 出卷 → 查看题目 + 展开完整执行轨迹 → 导出 Markdown
7. **在线答题**：学生账号选择已生成试卷作答 → 客观题规则判分 + 主观题溯源批改
8. **批改与成绩**：教师查看全班答卷 + 单份批改详情（得分/优缺点/课件原文引用）
9. **Agent 任务**：Agent 页提交任务，观察规划→执行→反思的执行轨迹
10. **审计日志**：审计页查看登录/上传/出卷/批改等全量操作记录与越权拦截

---

## 📊 实验与效果评估

实验设计指南详见 [docs/experiment_guide.md](docs/experiment_guide.md)，包含：召回准确率对比（BM25 vs 向量 vs 混合+重排）、分块策略对比、幻觉率评估、Agent 任务成功率与重试效果、双 Agent 出卷迭代收敛、并发 QPS 压测。

## 📝 毕业设计文档

- [系统架构设计说明](docs/architecture.md) — 论文《系统架构设计》章节
- [模块详细说明](docs/module_intro.md) — 论文《系统设计与实现》章节
- [实验设计指南](docs/experiment_guide.md) — 论文《实验与分析》章节
- [部署测试说明](docs/deploy.md) — 部署与连通性验证

---

## 📄 License

MIT License
