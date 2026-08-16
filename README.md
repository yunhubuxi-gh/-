# 课程试卷智能命题校验批改系统

> 基于**多模态 RAG + LangGraph 双 Agent** 的习题试卷智能处理平台
> 面向高校教师 / 学生 · 本科毕业设计 · 求职项目展示

**一句话简介**：上传课程讲义/课件（PDF、Word、扫描版、图片），系统自动解析文档、OCR 识别内嵌习题图片、构建多模态课程知识库，教师一键生成试卷（命题 Agent 出题 + 校验评审 Agent 逐题核验迭代），学生在线作答，客观题规则判分、主观题基于课件原文**溯源批改**。

---

## 🌟 项目简介

本系统在「企业私有知识库智能助手」底座之上，面向高校课程场景构建完整的 **命题 → 校验 → 答题 → 批改** 教学闭环：

- **教师侧**：上传课程讲义 / 课件（PDF、Word、Markdown、扫描版、图片）构建课程库，一键生成试卷 —— 命题 Agent 依据课件知识库出题，校验评审 Agent 逐题核验（知识点是否真实存在 / 答案是否正确 / 是否超纲 / 是否歧义），不合格题自动回传重生成；
- **学生侧**：在线作答，客观题由规则自动判分（不调用大模型），主观题由 RAG 检索课件原文 + 大模型**溯源批改**（得分 + 优缺点 + 课件原文引用）；
- **知识问答**：基于 BM25 + 向量 + 重排的混合检索增强生成，答案附带文档名 / 页码 / 原文片段引用；
- **多模态检索**：支持「文字描述 → 召回图片」，PDF / Word 内嵌图与 png/jpg 直接上传，OCR 文本通道与图片向量通道**双通道**入库，问答页直接渲染命中图片。

系统具备用户权限隔离（owner / admin / write / read 四级）、完整审计日志、后台异步任务、Docker 一键部署等工程化特性。底层 RAG / Agent / OCR 均**进程内本地推理**；图片多模态向量化支持**本地 Chinese-CLIP** 与**火山方舟豆包云端（doubao-embedding-vision）** 双后端可插拔切换（后者已实测通过，181 张内嵌图约 10 秒完成）。

---

## ✨ 项目亮点

1. **双 Agent 智能命题（LangGraph）**
   命题 Agent → 校验评审 Agent 两个**独立节点**在 LangGraph 中串联：命题 Agent 按题型多路 RAG 检索课件原文出题；校验评审 Agent 逐题 RAG 检索 + LLM 完成 4 项校验（知识点真实存在 / 答案正确 / 不超纲 / 无歧义），不合格题自动回传重生成（受 `EXAM_MAX_ITERATE` 上限约束）。完整执行轨迹（检索了什么 → 出了什么题 → 逐题校验 → 重生成）可逐轮展开，杜绝「大模型凭空出题」。

2. **Word / PDF 内嵌习题图片解析**
   - **PDF**：提取正文文本 + 文档内嵌习题图片，OCR 识别，文本分片，多模态图片向量化；
   - **docx（Word）**：解析 zip 包与 rels 关系，完整提取**段落内、表格内部**的全部内嵌截图习题（DrawingML `a:blip` 与 VML `v:imagedata` 双格式），正文 + 图片 OCR 文本**统一分片入库**，多模态向量化。

3. **强容错上传流水线**
   单张图片损坏、OCR 失败、API 限流、网络异常时，仅跳过该单张图片的向量化并记录警告，**整个文档上传任务不会失败**，正文文本与其余图片的 OCR 文本依旧正常入库。

4. **双可插拔多模态后端**
   图片向量化后端二选一，由 `.env` 的 `IMAGE_EMBED_PROVIDER` 配置切换：`doubao`（火山方舟云端多模态 Embedding，快、按量付费）或 `local`（本地 Chinese-CLIP，免费、CPU 较慢）。向量维度自动隔离（768 vs 1024/2048），`ENABLE_IMAGE_EMBED` 总开关一键关闭即退回纯文本 RAG，缺依赖也不报错。

5. **多路混合召回 + BGE 重排**
   BM25 关键词召回 + 向量语义召回双路融合（min-max 归一化加权），BGE-Rerank 精排，显著提升召回准确率、降低幻觉；回答标注文档名 + 页码 + 原文片段，有据可查。

6. **知识库溯源批改**
   客观题规则判分（选择题精确匹配、填空题关键词匹配，不调 LLM）；主观题 RAG 检索课件原文 + LLM 判分，每题附课件原文引用，杜绝「大模型凭空判分」。

7. **RBAC 权限系统 + 审计 + 异步任务**
   JWT 双令牌鉴权 + 知识库四级权限隔离（owner > admin > write > read）+ 完整审计日志（越权拦截可查）+ 后台异步任务（大文档向量化、整套出卷、批改不阻塞 HTTP）+ Docker Compose 一键部署。前端为**试卷主题登录页**（蓝灰教育风、居中卡片、系统能力简介）。

8. **可插拔工程化架构**
   向量库（Chroma / Milvus 二选一）、大模型（OpenAI 兼容协议，DeepSeek / Qwen / Ollama 等）、异步任务引擎（BackgroundTasks / Celery）均可配置切换；六层分层架构 + 三者分离存储（元数据 / 向量 / 文件）。

---

## 🛠 技术栈清单

| 层级 | 技术选型 | 版本 |
|------|---------|------|
| 语言 | Python | 3.10+ |
| 前端 | Streamlit（多页面 + 自定义 CSS 美化） | 1.61.1 |
| 后端 | FastAPI + Starlette + Uvicorn | 0.141.1 / 1.3.1 / 0.34.0 |
| 数据库 | PostgreSQL（生产）/ SQLite（开发，零依赖） | 16 / — |
| ORM | SQLAlchemy | 2.0.36 |
| 向量库 | Chroma（默认）/ Milvus（二选一） | 0.5.23 / 2.4.x |
| AI 编排框架 | LangGraph | 1.0.7 |
| AI 基础库 | LangChain-Core | 0.3.29 |
| 大模型 LLM | OpenAI 兼容协议（DeepSeek `deepseek-v4-flash` / `deepseek-v4-pro`） | — |
| 文本嵌入 | BGE-Embedding（sentence-transformers） | 3.3.1 |
| 重排模型 | BGE-Rerank（FlagEmbedding，缺模型自动降级词重叠打分） | 1.3.3（可选） |
| 多模态后端 | 火山方舟豆包云端 `doubao-embedding-vision-251215` / 本地 Chinese-CLIP | — |
| PDF 解析 | PyMuPDF | 1.24.10 |
| OCR | PaddleOCR（可选，扫描件文字识别） | 3.2.0 |
| 鉴权 | JWT 双令牌 + bcrypt | PyJWT 2.13.0 / bcrypt 4.0.1 |
| 异步任务 | BackgroundTasks（线程）/ Celery + Redis（可选） | — |
| 部署 | Docker Compose | — |

---

## 📋 功能模块列表

| 模块 | 说明 |
|------|------|
| **账号登录注册** | RBAC 四级权限（owner / admin / write / read），JWT 双令牌鉴权，试卷主题登录页 |
| **课程库管理** | 创建 / 编辑 / 删除课程库，成员管理与四级权限分配，课程标签 |
| **课件文档管理** | 上传 PDF / Word / Markdown / TXT / 图片，异步向量化 + 进度可视化，版本管理，重建索引 |
| **文档解析** | PDF 正文 + 内嵌图提取；docx zip-rels 完整提取段落/表格内图片；OCR 识别；文本分片 |
| **多模态检索** | 文本 BM25 + 文本向量 + 图片向量混合召回，BGE 重排，图片文字描述召回 + 前端渲染 |
| **智能问答** | 混合检索增强生成，答案带文档/页码/原文引用，幻觉抑制 |
| **智能试卷命题** | LangGraph 双 Agent 出卷 + 逐题校验 + 迭代重生成，完整执行轨迹可视化，导出 Markdown |
| **在线答题** | 学生选择试卷作答，客观题规则判分 |
| **自动批改** | 主观题 RAG 溯源批改（得分 + 优缺点 + 课件原文引用），全班成绩查看 |
| **Agent 任务** | 规划 → 执行 → 反思通用 Agent，短期记忆 + 长期记忆 |
| **审计日志** | 登录 / 上传 / 出卷 / 批改等全量操作记录与越权拦截记录 |
| **系统配置** | 通过 `.env` 集中管理：多模态后端、图片向量化总开关、LLM、向量库、重排、命题批改等参数 |

---

## 📷 系统截图

> 以下截图占位，请部署运行后自行截取并替换为真实图片。

```markdown
<!-- 登录页 -->
![登录页](docs/screenshots/login.png)

<!-- 课程库管理 -->
![课程库](docs/screenshots/kb.png)

<!-- 课件上传与向量化进度 -->
![课件上传](docs/screenshots/document_upload.png)

<!-- 智能问答（含图片召回） -->
![智能问答](docs/screenshots/chat.png)

<!-- 试卷生成（双 Agent 执行轨迹） -->
![试卷生成](docs/screenshots/exam_generate.png)

<!-- 答卷批改（溯源引用） -->
![答卷批改](docs/screenshots/grading.png)
```

---

## ⚙ 环境部署步骤

### 1. 环境依赖安装

**环境要求**：Python 3.10+（推荐 3.10）、Docker & Docker Compose（可选部署方式）。

```bash
# 1. 创建虚拟环境
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. 安装核心依赖（启用 Milvus / OCR / BGE-rerank / 图片向量化 需取消注释对应行）
pip install -r requirements.txt

# 3. 自检关键依赖（缺 PyMuPDF 会导致 PDF 解析失败，缺 sentence-transformers 会导致文本向量化失败）
python -c "import fitz, sentence_transformers, chromadb; print('核心依赖 OK')"
```

> 可选依赖（按需安装）：
> - **扫描件 OCR**：`pip install paddleocr==3.2.0 paddlepaddle==3.1.1 opencv-contrib-python==4.10.0.84 einops ftfy premailer`
> - **本地多模态（Chinese-CLIP）**：`pip install torch transformers modelscope pillow`（仅 `IMAGE_EMBED_PROVIDER=local` 需要）
> - **Milvus 向量库**：`pip install pymilvus==2.4.4`
> - **BGE-Rerank 精排**：`pip install FlagEmbedding==1.3.3`（缺失时自动降级为词重叠打分）

### 2. 配置 `.env` 文件

```bash
cp .env.example .env              # Windows: copy .env.example .env
```

编辑 `.env`，填入真实密钥与参数。**完整配置示例**（与 `.env.example` 一致，全部带注释）：

```ini
# ============================================================
# 应用基础
# ============================================================
APP_NAME=课程试卷智能命题校验批改系统
APP_VERSION=1.0.0
DEBUG=false
API_HOST=0.0.0.0
API_PORT=8000


# ============================================================
# 数据库连接（本地开发默认 SQLite，零依赖）
# ============================================================
DATABASE_URL=sqlite:///./data/app.db
# 生产 / Docker 用 PostgreSQL（docker-compose 内 host 为 postgres 服务名）：
# DATABASE_URL=postgresql://kbuser:kbpass123@localhost:5432/kb_assistant
# DATABASE_URL=postgresql://kbuser:kbpass123@postgres:5432/kb_assistant

POSTGRES_USER=kbuser
POSTGRES_PASSWORD=kbpass123
POSTGRES_DB=kb_assistant


# ============================================================
# JWT 鉴权（生产环境务必替换为足够长的随机字符串）
# ============================================================
JWT_SECRET_KEY=change-me-to-a-very-long-random-secret-string-32bytes-min
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=120
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7


# ============================================================
# DeepSeek 大模型（OpenAI 兼容协议）
# ------------------------------------------------------------
# ⚠️ DeepSeek 官方 API 仅提供「对话模型」deepseek-v4-flash / deepseek-v4-pro，
#    不提供 embedding / rerank 接口（请求返回 404）。
#    因此「嵌入」「重排」继续使用本地 BGE 模型，仅 LLM 对话走 DeepSeek。
# ============================================================
DEEPSEEK_API_KEY=sk-your-deepseek-api-key      # ← 必填：替换为你的真实 DeepSeek Key
DEEPSEEK_BASE_URL=https://api.deepseek.com

LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=                                  # 留空自动回退到 DEEPSEEK_API_KEY
LLM_MODEL=deepseek-v4-flash                   # 可选 deepseek-v4-pro
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=2048
LLM_TIMEOUT=60


# ============================================================
# 嵌入模型（Embedding）—— 本地 BGE
# ============================================================
EMBEDDING_PROVIDER=bge
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DIMENSION=512
EMBEDDING_BATCH_SIZE=8
HF_HUB_OFFLINE=true                            # HuggingFace 模型离线加载


# ============================================================
# 多模态图片向量化（可选：本地 Chinese-CLIP / 豆包云端）
# ------------------------------------------------------------
# 图片向量化后端二选一（图文同空间，支持「文字描述→召回图片」）：
#   local  ：本地 Chinese-CLIP，无需联网/付费，但 CPU 慢
#   doubao ：豆包云端多模态向量化（火山方舟），快、按量付费
#
# ⚠️ 切换后端需修改本文件并重启后端生效。
# ============================================================
ENABLE_IMAGE_EMBED=false                        # 图片向量化总开关（false 退回纯文本 RAG）
IMAGE_EMBED_PROVIDER=local                      # 图片向量化后端 local/doubao

# ---- 本地 Chinese-CLIP（IMAGE_EMBED_PROVIDER=local 时生效）----
CLIP_MODEL_NAME=damo/multi-modal_clip-vit-large-patch14_336_zh
CLIP_DEVICE=auto                                # auto/cuda/cpu
CLIP_MAX_IMAGE_SIDE=336                         # 图片预处理最大边长（防 OOM）
CLIP_MIN_IMAGE_SIDE=32                          # 过滤极小无效图
CLIP_DOWNLOAD_RETRY=3                           # 模型下载重试次数

# ---- 豆包云端多模态向量化（IMAGE_EMBED_PROVIDER=doubao 时生效）----
DOUBAO_API_KEY=                                 # 火山方舟 API Key（控制台完整复制）
# 接口地址二选一（勿混用，否则 401）：
#   标准方舟（按量付费）    : https://ark.cn-beijing.volces.com/api/v3
#   Agent Plan 个人版（套餐）: https://ark.cn-beijing.volces.com/api/plan/v3（含 /plan）
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_EMBEDDING_MODEL=doubao-embedding-vision-251215
DOUBAO_IMAGE_EMBED_DIM=1024                     # 向量维度 1024/2048
DOUBAO_TIMEOUT=60
DOUBAO_MAX_RETRY=3                              # 限流/超时自动重试次数
DOUBAO_IMAGE_MAX_SIDE=512                       # 图片压缩最大边长（越小越省钱）

IMAGE_VECTOR_TOP_K=5                            # 图片向量召回条数


# ============================================================
# 向量数据库（二选一：Chroma / Milvus）
# ============================================================
VECTOR_STORE_TYPE=chroma
CHROMA_PERSIST_DIR=./data/vector_store
# MILVUS_HOST=localhost
# MILVUS_PORT=19530
# MILVUS_ALIAS=default


# ============================================================
# BM25 关键词召回
# ============================================================
BM25_INDEX_DIR=./data/bm25_index
BM25_TOP_K=20


# ============================================================
# 重排模型（Rerank）—— 本地 BGE-Rerank
# ------------------------------------------------------------
# 模型缺失时自动降级为词重叠打分（OverlapReranker），保证重排始终可用。
# ============================================================
RERANKER_MODEL=BAAI/bge-reranker-base
RERANKER_TOP_N=5
RERANKER_DEVICE=cpu


# ============================================================
# RAG 通用
# ============================================================
CHUNK_SIZE=512
CHUNK_OVERLAP=50
SEMANTIC_CHUNK_THRESHOLD=0.75
MIN_CHUNK_SIZE=50
VECTOR_TOP_K=20
HALLUCINATION_CHECK_ENABLED=true

RERANK_CANDIDATE_K=20
RAG_CACHE_ENABLED=true
RAG_CACHE_TTL=300
RAG_CACHE_MAX_SIZE=512
RAG_DEBUG_LOG=false

QUERY_REWRITE_ENABLED=true
QUERY_REWRITE_COUNT=2
QUERY_REWRITE_TIMEOUT=10
QUERY_REWRITE_MAX_TOKENS=1024

VECTOR_BATCH_SIZE=256


# ============================================================
# 试卷命题 / 校验（双 Agent）配置
# ============================================================
EXAM_MAX_ITERATE=3                  # 双 Agent 最大迭代次数（防死循环）
EXAM_LLM_TIMEOUT=120                # 出题/校验 LLM 超时（秒）
EXAM_LLM_MAX_TOKENS=4096            # 出题/校验 LLM 最大输出 token
EXAM_RAG_TOP_K=6                    # 出题/校验时 RAG 召回课件原文条数
EXAM_TEMPERATURE=0.0                # 出题/校验 LLM 温度（0=稳定）
EXAM_DEFAULT_DIFFICULTY=medium      # 试卷默认难度 easy/medium/hard


# ============================================================
# Agent 配置
# ============================================================
AGENT_MAX_RETRY=3
AGENT_SHORT_TERM_MEMORY_WINDOW=10
AGENT_LONG_TERM_MEMORY_ENABLED=true
AGENT_MAX_PLAN_STEPS=5
AGENT_LONG_TERM_MAX_ITEMS=50
AGENT_LONG_TERM_DIR=./data/long_term_memory
AGENT_LONG_TERM_TOP_K=3


# ============================================================
# 异步任务（background = 线程；celery = 分布式）
# ============================================================
ASYNC_TASK_ENGINE=background
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1


# ============================================================
# OCR（扫描件文字识别）
# ============================================================
OCR_ENABLED=true
OCR_ENGINE=paddleocr
OCR_LANG=ch


# ============================================================
# 文件存储
# ============================================================
UPLOAD_DIR=./data/uploads
EXPORT_DIR=./data/exports
MAX_FILE_SIZE_MB=100
ALLOWED_FILE_TYPES=[".pdf",".docx",".md",".txt",".png",".jpg",".jpeg"]


# ============================================================
# 日志 / 审计
# ============================================================
LOG_LEVEL=INFO
LOG_DIR=./data/logs
AUDIT_LOG_ENABLED=true


# ============================================================
# 跨域 CORS
# ============================================================
FRONTEND_URL=http://localhost:8501
CORS_ORIGINS=["http://localhost:8501","http://127.0.0.1:8501"]


# ============================================================
# 前端配置
# ============================================================
FRONTEND_API_BASE_URL=
FRONTEND_TIMEOUT=60
FRONTEND_POLL_INTERVAL=1.0
FRONTEND_POLL_MAX_WAIT=180
```

> ⚠️ **密钥安全**：`DEEPSEEK_API_KEY` / `DOUBAO_API_KEY` / `JWT_SECRET_KEY` 均为敏感信息，**切勿提交到 GitHub**。本项目 `.env` 已在 `.gitignore` 中忽略，仓库只保留 `.env.example`（占位符版本）。

### 3. 启动项目

```bash
# 1. 初始化数据库（建表 + 创建默认管理员）
python -m db.init_db

# 2. 执行迁移（补 tags / processing_warning 列 + 建试卷/答卷表，幂等）
python -X utf8 scripts/migrate_course.py

# 3. 启动后端（另开终端）
python -X utf8 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 4. 启动前端（另开终端）
python -X utf8 -m streamlit run frontend/app.py --server.port 8501
```

访问地址：

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:8501 |
| 后端 API | http://localhost:8000 |
| API 文档（Swagger） | http://localhost:8000/docs |

### 方式二：Docker Compose 一键部署

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env：填 DEEPSEEK_API_KEY；数据库默认走容器内 PostgreSQL

# 2. 一键启动（自动编排 PostgreSQL + 后端 + 前端）
docker-compose up -d --build

# 3. 查看运行状态
docker-compose ps
```

---

## 📖 使用说明

### 1. 账号登录

首次启动由 `db/init_db.py` 自动创建默认账号，可直接用于快速上手演示：

| 账号 | 密码 | 角色 | 说明 |
|------|------|------|------|
| `admin` | `Teacher@123` | 管理员 / 教师（admin） | 全局管理，创建课程库后拥有 owner 全权限 |
| `demo` | `Student@123` | 学生（normal） | 被教师加为课程库 read 成员后在线答题 |
| `stu2` | `Student@123` | 学生（normal） | 第二名演示学生（测试用） |

> ⚠️ 生产环境请**立即修改默认密码**（登录后右上角「修改密码」），或删除默认账号。

### 2. 文档上传（PDF / Word / 图片）

1. 用 `admin` 登录 → 「课程库」创建课程库；
2. 进入「课件管理」→ 选择课程库 → 上传文档（PDF / Word / Markdown / TXT / 图片）；
3. 前端实时展示向量化进度：`解析文件 → 提取页面图片 → OCR 文字识别 → 文本分块 & 文本向量化 → 图片预处理 → 图片多模态 Embedding 向量化 → 写入向量库完成`；
4. 完成后文档状态为「就绪」，即可用于智能问答、生成试卷。

> **Word（docx）** 会解析 zip 包与 rels 关系，完整提取段落内、表格内的全部内嵌截图习题；每张图片 OCR 文字与正文**统一分片入库**，图片同时产生多模态向量，可被「文字描述 → 召回图片」命中。

### 3. 多模态后端切换

多模态图片向量化后端通过 `.env` 配置切换（**修改后需重启后端**）：

| 后端 | 配置 | 说明 |
|------|------|------|
| 本地 Chinese-CLIP | `IMAGE_EMBED_PROVIDER=local` | 免费，无需联网；CPU 较慢，建议有 GPU 或图片量小的场景 |
| 火山方舟豆包云端 | `IMAGE_EMBED_PROVIDER=doubao` + 填 `DOUBAO_API_KEY` | 快（181 张图约 10 秒），按量付费，需火山方舟 API Key |
| 关闭多模态 | `ENABLE_IMAGE_EMBED=false` | 退回纯文本 RAG，不加载多模态模型，缺依赖也不报错 |

> ⚠️ 切换后端需**重启后端**生效（`IMAGE_EMBED_PROVIDER` 在启动时读取）。
> ⚠️ 切换 provider 后旧图片向量维度不匹配（768 vs 1024/2048），需重新上传（或重建索引）才能被新后端检索到。

### 4. 智能生成试卷、校验批改试题操作流程

**出卷（教师）**：
1. `admin` 登录 → 「试卷中心」→ 选择课程库 + 题型数量（选择/填空/简答）+ 难度；
2. 提交后系统异步执行双 Agent 出卷，前端轮询展示进度；
3. 完成后查看题目、参考答案，展开查看**完整执行轨迹**（检索 → 出题 → 逐题校验 → 重生成）；
4. 支持导出 Markdown（可含/不含答案）。

**答题（学生）**：
1. `demo` / `stu2` 登录 → 「试卷中心」→ 选择已发布试卷在线作答 → 提交；
2. 客观题规则自动判分，主观题后台溯源批改。

**批改（教师）**：
1. `admin` 登录 → 「试卷中心」→ 「批改与成绩」查看全班答卷；
2. 单份答卷展开查看得分 + 优缺点 + 每题课件原文引用（溯源锚定）。

---

## ⚠️ 重要注意事项

### 1. 本地 Chinese-CLIP 内存问题

`IMAGE_EMBED_PROVIDER=local` 时，Chinese-CLIP 模型（约 1.2~1.6GB）在首次处理图片时从 modelscope 下载到本地缓存，CPU 环境下**多图场景容易内存占用过高甚至 OOM**，且速度较慢（181 张图约 10 分钟）。**演示 / 大批量推荐使用火山方舟豆包云端**（181 张图约 10 秒）；本地模式适合后续迭代优化。

### 2. 云端模式需火山方舟 API Key

`IMAGE_EMBED_PROVIDER=doubao` 需填写火山方舟 `DOUBAO_API_KEY`。注意**接口地址不能混用**：标准方舟（按量付费）为 `/api/v3`，Agent Plan 个人版（套餐）为 `/api/plan/v3`，Coding Plan 为 `/api/coding/v3`，混用会返回 401。

### 3. 文档上传容错

单张图片损坏、OCR 失败、API 限流、网络异常时，系统**仅跳过该单张图片的向量化**并记录警告，整个文档上传任务不会失败，正文文本与其余图片的 OCR 文本依旧正常入库（文档状态为「就绪」+ 前端 ⚠️ 警告）。

### 4. DeepSeek 推理模型思考模式

`deepseek-v4-flash` / `deepseek-v4-pro` 为推理模型，默认开启思考模式，`reasoning_content` 会先于 `content` 输出，可能导致结构化 JSON 输出为空。本项目已在出题 / 校验 / 批改节点的 LLM 调用中显式**关闭思考模式**（`thinking={"type":"disabled"}`），保证稳定输出。

### 5. 密钥安全

切勿将 `.env`（含真实 `DEEPSEEK_API_KEY` / `DOUBAO_API_KEY` / `JWT_SECRET_KEY`）提交到 GitHub；仓库仅保留 `.env.example` 占位模板。

---

## 📁 项目目录结构

```
enterprise-kb-assistant/
├── ai/                          # AI 能力层
│   ├── rag_engine/              #   RAG 引擎（解析/分块/召回/重排/图片检索/幻觉抑制）
│   │   ├── document_parser/     #     文档解析器（PDF/DOCX/MD/TXT/图片 + OCR）
│   │   ├── chunker/             #     分块器（语义分块 + 递归分块兜底）
│   │   ├── vector_store/        #     向量库（Chroma / Milvus 二选一）
│   │   ├── image_preprocess.py  #     图片预处理（过滤极小图/等比例缩放，仅 PIL）
│   │   └── image_retriever.py   #     图片多模态检索（独立集合 kb_{id}_img）
│   └── agent_langgraph/         #   Agent 智能层
│       ├── exam/                #     双 Agent 命题-校验-重生成 + 主观题批改
│       └── ...                  #     规划→执行→反思通用 Agent + 工具 + 记忆
├── api/                         # API 接口层（FastAPI）
│   ├── main.py                  #   主入口（中间件/路由/异常处理）
│   ├── deps.py                  #   JWT 鉴权依赖
│   └── router/                  #   路由（auth/kb/document/exam/chat/agent/audit）
├── services/                    # 业务服务层（含 exam_service 出卷/批改）
├── db/                          # 数据持久层
│   ├── models.py                #   ORM 模型（含 ExamPaper / AnswerSheet）
│   ├── schemas.py               #   Pydantic DTO
│   ├── crud/                    #   数据访问层（含 exam_crud）
│   ├── session.py               #   会话管理
│   └── init_db.py               #   数据库初始化（建表 + 管理员）
├── utils/                       # 通用工具层
│   ├── multimodal_embedding_client.py   # 多模态客户端（Chinese-CLIP / 豆包双后端）
│   ├── doubao_embedding_client.py       # 豆包云端多模态 Embedding 客户端
│   ├── ocr_engine.py            #   OCR 引擎（PaddleOCR / Tesseract）
│   ├── llm_client.py            #   LLM 客户端（OpenAI 兼容）
│   └── ...
├── config/                      # 配置层（settings + constants + logging）
├── frontend/                    # UI 表现层（Streamlit）
│   ├── app.py                   #   主入口（课程库/课件/试卷/问答/Agent/审计）
│   ├── pages/                   #   6 大页面
│   ├── styles.py                #   全局自定义 CSS
│   └── api_client.py            #   HTTP 请求封装
├── scripts/                     # 迁移脚本（migrate_course.py 等，幂等）
├── tests/                       # 分步骤测试（test_step1 ~ test_step6）
├── docs/                        # 毕设文档（架构/模块/实验/部署）
├── demo_docs/                   # 演示用示例文档
├── Dockerfile                   # 后端镜像
├── docker-compose.yml           # 一键编排（PG + 后端 + 前端）
├── requirements.txt             # 依赖清单（核心依赖锁定，可选依赖注释化）
├── MODIFY_LIST.md               # 改造修改清单
├── TEST_GUIDE.md                # docx 文档处理测试指南
├── TEST_IMAGE_GUIDE.md          # 图片多模态测试指南
├── .env.example                 # 环境变量模板
└── .gitignore
```

---

## 🧪 测试说明

项目按 6 个开发步骤配套 6 个测试脚本，覆盖各层核心能力，全部离线可跑（注入 Fake 组件，不依赖真实模型/向量库）：

```bash
python tests/test_step1_utils.py     # Utils 工具层
python tests/test_step2_db.py        # 数据库层（ORM/CRUD）
python tests/test_step3_rag.py       # RAG 引擎（解析/分块/召回/重排/幻觉抑制）
python tests/test_step4_agent.py     # Agent 智能层（状态图/工具/记忆/反思重试）
python tests/test_step5_services.py  # 业务服务层（鉴权/权限隔离/上传/问答/审计）
python tests/test_step6_api.py       # API 接口层（鉴权/权限/异常格式）
```

专项测试指南：

- [TEST_IMAGE_GUIDE.md](TEST_IMAGE_GUIDE.md) — 图片多模态向量化（含图 PDF 子状态与部分损坏降级、jpg 召回、开关回退、模型下载失败降级）
- [TEST_GUIDE.md](TEST_GUIDE.md) — docx（Word）文档处理（多图 docx 分块 + 图片 OCR 入库、损坏图降级、local/volcano 双后端切换、开关关闭回退、PDF 回归）

---

## 📌 未来优化方向

- **进一步优化本地 Chinese-CLIP 内存占用与推理速度**：解决 CPU 多图 OOM 与内存泄漏问题，探索 ONNX / TensorRT 量化推理；
- **支持更多文件格式**：PPT（`.pptx`）讲义解析、Excel（`.xlsx`）题库导入、LaTeX 数学公式解析；
- **多模态后端运行时热切换**：目前切换 local/volcano 需改 `.env` + 重启，未来可增加「系统设置」页面与运行时配置接口，实现前端无感切换；
- **试卷题目质量评估**：引入更细粒度的题目难度/区分度/知识点覆盖度评估指标，实验对比不同分块与召回策略；
- **批改能力增强**：主观题分步给分、公式/代码题自动判分、相似作答聚类分析；
- **分布式部署**：Celery + Redis 异步任务集群、Milvus 向量库水平扩展、GPU 推理加速；
- **前端体验**：流式问答打字机效果、试卷在线导出 PDF / Word、成绩统计分析图表。

---

## 📃 许可证

本项目采用 [MIT License](LICENSE) 开源协议。你可以自由使用、修改与分发，但请保留原作者版权声明。
