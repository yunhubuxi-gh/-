# 修改清单 — 课程试卷智能命题校验批改系统改造

> 日期：2026-08-15
> 范围：将「企业私有知识库智能助手」改造为「课程试卷智能命题校验批改系统」，覆盖两阶段：
> **阶段1** 课程库改造 + LangGraph 双 Agent 命题-校验-迭代重生成 + 试卷管理；
> **阶段2** 学生在线答题 + 客观题规则判分 + 主观题知识库溯源批改。
>
> 硬性约束（严格遵守）：
> - 底层 `ai/rag_engine`（BM25+向量+Rerank 混合检索）、LangGraph 框架、Chroma、RBAC 四级权限、异步任务、审计日志、文档解析、OCR **全部保留复用，未重写**；对外接口入参/返回值不变。
> - 双 Agent 是**两个独立节点**在 LangGraph 中串联，**未合并成单轮 LLM 调用**。
> - 出题/校验/批改均调用 RAG 检索私有课件，**禁止大模型凭内部知识出题**（prompt 反复强调 + 溯源锚定）。
> - 密钥/模型/开关全部读 `.env`，无硬编码。
> - 所有耗时操作（上传课件、整套出卷、批改答卷）均走后台异步任务。

---

## 一、数据库变更 SQL（ALTER / CREATE）

> 项目无 Alembic，用轻量迁移脚本 `scripts/migrate_course.py` 幂等执行（`create_all` 建新表 + 显式 `ALTER TABLE` 补列）。等价 SQL 如下：

### 1. 扩展已有表（ALTER）

```sql
-- PostgreSQL
ALTER TABLE knowledge_bases ADD COLUMN tags JSON;         -- 课程标签（字符串数组）
ALTER TABLE answer_sheets  ADD COLUMN error_message TEXT; -- 批改失败原因

-- SQLite（无原生 JSON，用 TEXT 存 JSON 字符串）
ALTER TABLE knowledge_bases ADD COLUMN tags TEXT;
ALTER TABLE answer_sheets  ADD COLUMN error_message TEXT;
```

### 2. 新建表（CREATE，由 Base.metadata.create_all 自动生成）

```sql
-- PostgreSQL 方言（SQLite 对应 SERIAL→INTEGER AUTOINCREMENT、JSON→TEXT、now()→CURRENT_TIMESTAMP）
CREATE TABLE exam_papers (
    id                SERIAL PRIMARY KEY,
    created_at        TIMESTAMP NOT NULL DEFAULT now(),
    updated_at        TIMESTAMP NOT NULL DEFAULT now(),
    is_deleted        BOOLEAN   NOT NULL DEFAULT false,
    knowledge_base_id INTEGER   NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    creator_id        INTEGER            REFERENCES users(id) ON DELETE SET NULL,
    title             VARCHAR(256) NOT NULL,
    question_config   JSON,                      -- {choice, fill, short}
    difficulty        VARCHAR(32)  NOT NULL DEFAULT 'medium',
    questions         JSON,                      -- [{qid,type,stem,options,answer,knowledge_point,source_refs}]
    reference_answers JSON,                      -- 参考答案（与题目对应，可单独导出）
    trace             JSON,                      -- 双 Agent 完整执行轨迹
    iterate_count     INTEGER DEFAULT 0,
    total_score       INTEGER DEFAULT 0,
    status            VARCHAR(32)  NOT NULL DEFAULT 'generating',  -- generating/ready/failed
    error_message     TEXT
);

CREATE TABLE answer_sheets (
    id               SERIAL PRIMARY KEY,
    created_at       TIMESTAMP NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP NOT NULL DEFAULT now(),
    is_deleted       BOOLEAN   NOT NULL DEFAULT false,
    exam_paper_id    INTEGER   NOT NULL REFERENCES exam_papers(id) ON DELETE CASCADE,
    student_id       INTEGER            REFERENCES users(id) ON DELETE SET NULL,
    answers          JSON,                       -- 学生作答 [{qid, answer}]
    objective_score  INTEGER DEFAULT 0,
    subjective_score INTEGER DEFAULT 0,
    total_score      INTEGER DEFAULT 0,
    grading_details  JSON,                       -- [{qid,score,strengths,missing,source_refs}]
    status           VARCHAR(32) NOT NULL DEFAULT 'submitted',  -- submitted/grading/graded/failed
    error_message    TEXT,
    submitted_at     TIMESTAMP
);
```

---

## 二、本次修改清单

### 2.1 数据模型层

| 文件 | 变更内容 | 类型 |
|------|---------|------|
| `config/constants.py` | 新增 `ExamPaperStatus`/`ExamQuestionType`/`ExamDifficulty`/`AnswerSheetStatus`（含 FAILED）/`DEFAULT_QUESTION_SCORE`；`AuditAction` 新增 `exam_generate/update/delete/submit/grade`；`TaskType` 新增 `exam_generate/exam_grade` | 修改 |
| `config/settings.py` | 新增 `exam_max_iterate`/`exam_llm_timeout`/`exam_llm_max_tokens`/`exam_rag_top_k`/`exam_temperature`/`exam_default_difficulty` 配置 | 修改 |
| `db/models.py` | `KnowledgeBase` 加 `tags`（JSON）；新增 `ExamPaper`、`AnswerSheet` 两表 | 修改 |
| `db/schemas.py` | `KB*` 加 `tags`；新增 `ExamQuestionConfig`/`ExamPaperCreate/Update/Response/DetailResponse`/`AnswerSheetSubmit/Response` | 修改 |
| `db/crud/exam_crud.py` | 新增 `ExamPaperCRUD` + `AnswerSheetCRUD`（题目/轨迹/判分结果读写） | 新增 |
| `db/crud/__init__.py` | 注册 `exam_paper_crud` / `answer_sheet_crud` | 修改 |
| `scripts/migrate_course.py` | 轻量迁移脚本（补 tags 列 + 建新表 + 补 error_message 列，幂等） | 新增 |

### 2.2 双 Agent 工作流 + 主观题批改（`ai/agent_langgraph/exam/`）

| 文件 | 变更内容 | 类型 |
|------|---------|------|
| `state.py` | `ExamState` TypedDict（`trace` 用 `Annotated[List, operator.add]` 追加语义） | 新增 |
| `json_util.py` | LLM JSON 多格式兜底解析（剥 fence / 截取 {} [] / 兼容 `{questions:[...]}` 与 `[...]`） | 新增 |
| `rag_util.py` | 多查询 RAG 检索 + 去重拼接课件原文 + 检索日志 | 新增 |
| `generator_node.py` | **命题 Agent**：按题型主动多次 RAG 检索 → LLM 出题（题目+答案+知识点+来源引用）→ 迭代时仅重生成不合格题 | 新增 |
| `validator_node.py` | **校验评审 Agent**：逐题 RAG 检索 + LLM 4 项校验（①知识点真实存在②答案正确③不超纲④无歧义） | 新增 |
| `graph_builder.py` | `build_exam_graph`：`START→generator→validator`，条件边 `validator→generator`（不合格且未达上限）/ `END` | 新增 |
| `exam_manager.py` | `ExamManager.execute` 组装依赖→建图→invoke→提取题目/轨迹/迭代次数，异常标准化不崩溃 | 新增 |
| `grader.py` | `GradeManager.grade_subjective`：RAG 检索课件 → LLM 判分 → 溯源锚定（编造引用过滤）→ 空响应重试 | 新增 |
| `__init__.py` | 导出 `ExamManager`/`GradeManager`/`build_exam_graph` | 新增 |

### 2.3 服务层 / API 层

| 文件 | 变更内容 | 类型 |
|------|---------|------|
| `services/exam_service.py` | `generate`（write+ 权限）→ 后台 `_generate_task`；`list/get/update/delete/export_markdown`；`submit_answer`（客观题规则判分）→ 后台 `_grade_task`（主观题溯源批改）；`list_answers/get_answer`；read 角色隐藏答案/参考答案/导出去答案 | 新增 |
| `services/__init__.py` | 注册 `exam_service` | 修改 |
| `api/router/exam_router.py` | 9 端点：生成/列表/详情/更新/删除/导出/提交答卷/全班答卷/答卷详情 | 新增 |
| `api/router/__init__.py` | 导出 `exam_router` | 修改 |
| `api/main.py` | 注册 `/api/v1/exam` 路由 | 修改 |
| `utils/error_codes.py` | 新增 17 号段（试卷/答卷/批改） | 修改 |

### 2.4 前端（Streamlit）

| 文件 | 变更内容 | 类型 |
|------|---------|------|
| `frontend/app.py` | 页面标题「课程试卷智能命题校验批改系统」；PAGES 注册「📝 试卷中心」；侧边栏品牌改名 | 修改 |
| `frontend/pages/kb_page.py` | 文案「知识库」→「课程库」；创建表单加「课程标签」输入；卡片/详情展示标签 | 修改 |
| `frontend/pages/exam_page.py` | 三标签页：**试卷管理**（生成表单+进度轮询+历史+轨迹展开+导出）、**在线答题**（选择试卷→作答→提交→批改轮询）、**批改与成绩**（教师看全班答卷+单份溯源明细） | 新增 |

### 2.5 配置

| 文件 | 变更内容 | 类型 |
|------|---------|------|
| `.env.example` / `.env` | 新增「试卷命题/校验（双 Agent）」配置块（`EXAM_*` 6 项，全带注释） | 修改 |

---

## 三、LangGraph 双 Agent 图逻辑（核心，禁止简化）

```text
                    ┌──────────────────────────────────────────┐
                    │  ExamManager.execute(kb_id, cfg, diff)    │
                    │  组装 ExamDependencies（llm+rag+上限）      │
                    └──────────────────┬───────────────────────┘
                                       │ graph.invoke(initial_state)
                                       ▼
                              ┌────────────────┐
                    START ───▶│  generator      │  命题 Agent
                              │  ① 按题型多路 RAG 检索课件原文
                              │  ② LLM 出题(题+答案+知识点+来源引用)
                              │  ③ 迭代时仅重生成 rejected 题(保持 qid)
                              └───────┬────────┘
                                      │ questions
                                      ▼
                              ┌────────────────┐
                              │  validator      │  校验评审 Agent
                              │  逐题 RAG 检索 + LLM 4 项校验
                              │  输出 {qid, verdict, reason, source_refs}
                              └───────┬────────┘
                                      │ route_after_validator
              ┌───────────────────────┴───────────────────────┐
              │  rejected 非空 且 iterate < max_iterate？        │
              │  是 → 回 generator（仅重生成不合格题）            │
              │  否 → END                                       │
              └────────────────────────────────────────────────┘
```

- 两个节点 `generator` / `validator` 为**独立 Agent**，通过 `add_conditional_edges` 串联，各自独立调用 LLM + RAG，**绝不合并成单轮调用**。
- 迭代由 `ExamState.max_iterate`（读 `.env` 的 `EXAM_MAX_ITERATE`）硬上限，防死循环。
- 每轮 `generation`/`validation` 均向 `trace` 追加记录，前端可逐轮展开「检索了什么→出了什么题→逐题校验→重生成」。

---

# 修改清单 — 图片多模态向量化（Chinese-CLIP 本地推理，可开关可选模块）

> 日期：2026-08-15
> 范围：在既有「文本 RAG + BM25/向量/Rerank 混合检索 + 双 Agent 试卷业务」之上，**新增可开关的图片多模态向量化/检索能力**。
> 硬性约束（严格遵守）：
> - 原有全部业务 100% 保留，绝不破坏现有链路：文本 RAG、BM25+向量+rerank 混合检索、LangGraph 双 Agent、RBAC、异步任务、审计日志、PaddleOCR、数据库、前端页面全部保留。
> - 图片多模态为**可选模块**，由 `.env` 的 `ENABLE_IMAGE_EMBED` 控制；`false` 时完全走旧逻辑，不加载 CLIP、不执行图片向量、不导入 CLIP 相关库，完全回退且不报错。
> - 使用 modelscope 开源 `damo/multi-modal_clip-vit-large-patch14_336_zh`，**进程内本地推理**，严禁 Ollama、禁止调用任何外部图片 Embedding API。
> - 容错降级【最重要】：单张图片向量化任何异常不导致整个上传异步任务失败；失败仅跳过该图向量，仍继续 OCR/文本分块/文本向量化，文档整体摄入必须完成；日志明确打印哪张图失败+原因，前端任务状态标记警告而非失败。
> - 原始图片持久化保存在本地上传目录；Chroma 只存向量+元数据，**禁止把图片二进制存入向量库**。
> - 所有模型路径/开关/超时/图片大小限制全放 `.env`，禁止硬编码。
> - 自动设备检测：优先 cuda；无 GPU 自动降级 CPU 并日志提示。

---

## 一、新增模块

| 文件 | 职责 | 类型 |
|------|------|------|
| `ai/rag_engine/image_preprocess.py` | 图片预处理（**仅用 PIL，不依赖 torch**）：过滤极小图（`CLIP_MIN_IMAGE_SIDE`）、等比例缩放最大边长至 `CLIP_MAX_IMAGE_SIDE`（LANCZOS）、转 RGB、存 PNG 副本。`preprocess_image(bytes, out, max_side, min_side) -> (ok, msg)` **永不抛异常** | 新增 |
| `utils/multimodal_embedding_client.py` | Chinese-CLIP 客户端（**懒加载**）：modelscope `snapshot_download` 下载（带 `CLIP_DOWNLOAD_RETRY` 重试）→ `ChineseCLIPModel/ChineseCLIPProcessor` 本地加载 → `embed_images/embed_texts`（逐张 try-except，失败返回空向量）。`get_multimodal_client()` 先查 `enable_image_embed` 再导入 torch/transformers/modelscope（**函数内局部导入**） | 重写 |
| `ai/rag_engine/image_retriever.py` | 图片向量写入与检索：`index_images(...) -> (count, warnings)`（逐张 try-except，元数据带 `chunk_type="image"`+`content_type="image"`+`source_file`+`page_num`+`image_path`+`format`）；`retrieve_images(...)`（逐 kb try-except） | 重写 |

## 二、开关逻辑（`ENABLE_IMAGE_EMBED`）

```text
ENABLE_IMAGE_EMBED=false（默认）
  ├─ 上传文档：PDF 只走 文本提取 + 页面图片→OCR→文本 chunk；直接上传图片只走 原图保存 + OCR 文本 chunk
  ├─ 不调用 get_multimodal_client()，不 import torch/transformers/modelscope（缺依赖也能正常启动）
  ├─ rag_pipeline._retrieve_images 直接 return []（图片检索分支完全不执行）
  └─ 与改造前行为完全一致，零风险回退

ENABLE_IMAGE_EMBED=true
  ├─ 上传文档：在原有 OCR 文本链路之外，新增 图片预处理 → CLIP 向量 → 写入 Chroma 图片集合 kb_{id}_img
  ├─ RAG 检索：原有 BM25+向量+rerank 完全不动，追加图片检索分支（CLIP 文本向量→查图片集合→合并去重→每条结果加 content_type/image_path）
  ├─ CLIP 懒加载：首次处理图片才下载/加载（非服务启动）；失败则关闭图片向量化、日志警告、文本业务继续
  └─ 前端：问答组件渲染 content_type=image 的图片；异步任务页展示「部分图片向量化失败」警告
```

## 三、降级容错策略（重点）

| 场景 | 行为 |
|------|------|
| 单张图片向量化抛异常（模型下载失败/内存不足/图片损坏/尺寸超限） | **跳过该图向量**，不导致上传任务失败；继续 OCR/文本分块/文本向量化，文档整体摄入完成 |
| 图片向量化全部失败 | 文档仍 `ready`，`processing_warning` 写入「部分图片向量化失败（共 N 张），文本内容已正常入库。详情：…」，前端 `st.warning` 展示 |
| CLIP 模型下载失败 / 加载失败 | `get_multimodal_client()` 捕获异常 → 关闭图片向量化开关 → 日志 WARNING → 系统继续文本业务，不崩溃 |
| `ENABLE_IMAGE_EMBED=false` | 完全不执行 CLIP 代码路径、不导入 CLIP 相关库，缺依赖也不报错 |
| 图片预处理失败（PIL 异常） | `preprocess_image` 返回 `(False, 原因)`，跳过该图，不影响其它图 |

## 四、异步任务细粒度子状态

上传/重建文档时后台任务逐段上报（`DocumentStatus` 新增 `IMAGE_PREPROCESS`）：

```text
解析文件 → 提取页面图片 → OCR文字识别 → 文本分块&文本向量化
         → 图片预处理 → 图片多模态Embedding向量化 → 写入向量库完成
```

前端 `document_page.py` 状态映射与 `components.py` 徽章已补齐 `image_preprocess`/`image_embedding`。

## 五、数据库 / 配置 / 部署变更

| 文件 | 变更内容 | 类型 |
|------|---------|------|
| `db/models.py` | `Document` 加 `processing_warning`（Text，可空） | 修改 |
| `db/crud/document_crud.py` | `update_status` 增加 `warning` 参数，写入 `processing_warning` | 修改 |
| `scripts/migrate_course.py` | 新增幂等 `add_document_warning_column()`（ALTER TABLE documents ADD COLUMN processing_warning TEXT） | 修改 |
| `config/settings.py` | 新增 `enable_image_embed`/`clip_model_name`/`clip_device`/`clip_max_image_side`/`clip_min_image_side`/`clip_download_retry` + 兼容旧字段 | 修改 |
| `config/constants.py` | `DocumentStatus` 新增 `IMAGE_PREPROCESS` | 修改 |
| `.env.example` / `.env` | 新增 CLIP 配置块（全带注释）+ 兼容旧 `MULTIMODAL_*`/`IMAGE_MAX_SIDE` 注释 | 修改 |
| `requirements.txt` | 新增可选块：`torch`/`transformers`/`modelscope`/`pillow`（**默认注释**，懒加载，缺省不影响启动） | 修改 |
| `Dockerfile` | 注释标注 CLIP 为可选依赖（不装保持镜像精简） | 修改 |
| `docker-compose.yml` | 透传 `ENABLE_IMAGE_EMBED`/`CLIP_MODEL_NAME`/`CLIP_DEVICE`/`CLIP_MAX_IMAGE_SIDE`/`CLIP_MIN_IMAGE_SIDE`/`CLIP_DOWNLOAD_RETRY` | 修改 |

## 六、对原有 RAG 链路的影响（零破坏声明）

- `ai/rag_engine/hybrid_retriever.py`（BM25+向量+融合+rerank）**未改动**，`RetrievedChunk.metadata` 已能透传 `content_type`/`image_path`。
- `rag_pipeline.retrieve()` 仅在 `ENABLE_IMAGE_EMBED=true` 时追加图片检索分支，关闭时行为与旧版一致。
- 文本文档的上传/分块/向量化/检索链路完全未改。

---

# 修改清单 — 环境依赖修复（PyMuPDF + HuggingFace 离线加载）

> 日期：2026-08-16
> 范围：修复两个导致「PDF/图片向量化失败」的环境依赖问题。均不影响业务代码结构，仅补齐依赖与 HF 离线加载时序。

## 一、问题与根因

| 现象 | 根因 | 修复 |
|------|------|------|
| PDF 上传报 `[1300005] PyMuPDF 未安装`，文档处理失败 | 环境缺少 `pymupdf`（`import fitz`），`requirements.txt` 虽声明但未实际安装 | 补装 `PyMuPDF==1.24.10` |
| 文本向量化失败，日志 `huggingface.co ... SSL: CERTIFICATE_VERIFY_FAILED` | BGE 模型已本地缓存，但加载时仍联网去 huggingface.co 校验；且 `HF_HUB_OFFLINE` 之前在客户端 `__init__` 才设置，**晚于** huggingface_hub 导入（库在导入时就把该值读成常量） | 将 `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` 的设置提前到 `config/settings.py` **模块加载时** |

## 二、变更清单

| 文件 | 变更内容 | 类型 |
|------|---------|------|
| `config/settings.py` | 新增 `hf_hub_offline: bool = True` 配置；模块加载末尾（`settings = get_settings()` 之后）立即写 `os.environ.setdefault("HF_HUB_OFFLINE"/"TRANSFORMERS_OFFLINE", "1")`，早于任何 HF 库导入 | 修改 |
| `utils/embedding_client.py` | 新增 `_apply_hf_offline()`，`BgeEmbeddingClient.__init__` 调用（保留兜底，双保险） | 修改 |
| `ai/rag_engine/reranker/bge_reranker.py` | `BgeReranker.__init__` 在加载 FlagReranker 前写 `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` | 修改 |
| `.env` / `.env.example` | 新增 `HF_HUB_OFFLINE=true` 配置项 + 注释 | 修改 |
| `README.md` | 「快速开始」加核心依赖自检；「关键配置」加 HF 离线加载小节；新增「常见问题（环境依赖）」 | 修改 |

## 三、关键设计说明

- **时序**：`huggingface_hub` / `transformers` / `sentence_transformers` 在**导入时**就把 `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` 读成模块级常量，因此必须在这类库被 import **之前**设置环境变量。本项目统一在 `config.settings` 模块加载时设置（该模块是最早被 import 的入口之一），从根上解决。
- **双保险**：`utils/embedding_client.py` 与 `bge_reranker.py` 的客户端构造里仍保留设置，防止未来有绕过 settings 的直接 import 场景。
- **零破坏**：`HF_HUB_OFFLINE=false` 时行为与旧版完全一致（允许联网）；仅当 `true` 时强制离线用本地缓存。

## 四、验证结果

| 场景 | 结果 |
|------|------|
| 含内嵌图片 PDF 上传 | ✅ `ready`：文本 1 chunk + 图片 1 张，警告 0 |
| 直接上传 png | ✅ `ready`：图片向量化 成功=1 失败=0 |
| 文字描述「黄色的猫」检索 | ✅ 召回 2 张图片（`content_type=image`）+ 1 条文本 |

---

# 修改清单 — 图片向量化后端可插拔（豆包云端多模态）

> 日期：2026-08-16
> 范围：在既有「本地 Chinese-CLIP 图片向量化」基础上，新增**豆包（火山方舟）云端多模态向量化**后端，
> 由 `IMAGE_EMBED_PROVIDER` 二选一（local / doubao），解决大批量图片在 CPU 上向量化过慢（181 张约 10 分钟）的问题。

## 一、动机

本地 Chinese-CLIP 是 ViT-Large/14@336（24 层 Transformer），CPU 上每张图数秒；含 181 张内嵌图的课件 PDF
向量化约 10 分钟，前端长时间卡在「图片向量化中」。豆包 `doubao-embedding-vision` 云端 GPU 推理，
图文同空间，同样支持「文字描述 → 召回图片」，181 张图约 10 秒。

## 二、方案要点

| 项 | 说明 |
|----|------|
| 后端选择 | `IMAGE_EMBED_PROVIDER=local`（本地 CLIP）或 `doubao`（豆包云端） |
| 豆包模型 | `doubao-embedding-vision-251215`，图文同空间，维度 `DOUBAO_IMAGE_EMBED_DIM`（1024/2048） |
| 接口 | 火山方舟 Ark 多模态向量化 `POST /embeddings/multimodal`，图片 base64 上传 |
| 地址 | 标准方舟 `/api/v3`；Agent Plan 个人版专属 `/api/plan/v3`（实测通过，勿混用） |
| 省钱措施 | 图片先等比压缩（默认长边 512 + JPEG q85）再上传，降低像素面积计费；限流/超时自动重试 |
| 维度隔离 | 图片集合名带维度 `kb_{id}_img_{dim}`，local(768) 与 doubao(1024) 互不干扰 |
| 无本地依赖 | provider=doubao 时**不导入 torch/transformers/modelscope**，纯 requests 调用 |

## 三、变更清单

| 文件 | 变更内容 | 类型 |
|------|---------|------|
| `config/settings.py` | 新增 `image_embed_provider`（local/doubao）+ `doubao_api_key/base_url/embedding_model/image_embed_dim/timeout/max_retry/image_max_side` 共 7 项配置 | 修改 |
| `utils/doubao_embedding_client.py` | 新增 `DoubaoEmbeddingClient`：纯 requests 调 Ark embeddings，`embed_image/embed_images/embed_query/embed_texts` + `dimension`，图片压缩 + 限流退避重试，逐张 try-except | 新增 |
| `utils/multimodal_embedding_client.py` | `get_multimodal_client()` 改为按 provider 分发的工厂：doubao 分支不导入 torch/CLIP | 修改 |
| `ai/rag_engine/image_retriever.py` | `_img_collection(kb_id, dim)` 集合名带维度隔离；`index_images`/`retrieve_images` 用 `client.dimension`；`clear_document_images` 清理 768/1024/2048 全部旧集合 | 修改 |
| `.env` / `.env.example` | 新增 `IMAGE_EMBED_PROVIDER` + `DOUBAO_*` 配置块（带注释） | 修改 |
| `README.md` | 「图片多模态向量化开关」改写为二选一方案 + 省钱/切换说明 | 修改 |

## 四、兼容性（零破坏）

- `IMAGE_EMBED_PROVIDER=local`（默认）时行为与之前完全一致，本地 CLIP 链路不受影响。
- `ENABLE_IMAGE_EMBED=false` 时依旧全量回退，local 不导入 torch、doubao 不联网。
- 图片检索链路（`rag_pipeline → image_retriever → client.embed_query`）对两种后端透明，无需改动。
- 旧集合名 `kb_{id}_img`（无维度后缀）仍被 `clear_document_images` 清理，不产生孤儿向量。

## 五、待办（依赖用户提供有效 Key）

- 当前 `.env` 中 `DOUBAO_API_KEY` 留空。用户提供的 key 实测返回 401（疑似复制截断），
  待提供完整有效的火山方舟 API Key 后填入即可启用 doubao 后端。

---

*以下为更早的历史变更清单（课程试卷系统改造、DeepSeek 对接、RAG 引擎优化），保留备查。*

---

# 修改清单 — DeepSeek API 对接配置适配

> 日期：2026-08-15
> 范围：仅做 DeepSeek API 配置适配（读取 / 校验 / 调用链路），不涉及检索、分块、混合检索等业务逻辑改动，不做性能优化。

---

## 一、核心结论（实测，重要）

实测 DeepSeek 官方 API（`https://api.deepseek.com`）：

| 接口 | 结果 |
|------|------|
| `GET /models` | 仅返回 `deepseek-v4-flash`、`deepseek-v4-pro`（均为对话模型） |
| `POST /embeddings` | HTTP 404 |
| `POST /rerank` | HTTP 404 |

因此本项目的 DeepSeek 对接方案为：

| 能力 | 对接方式 | 状态 |
|------|---------|------|
| LLM（对话） | DeepSeek `deepseek-v4-flash` | ✅ 可用 |
| Embedding（嵌入） | 本地 BGE `BAAI/bge-small-zh-v1.5` | ✅ 已缓存可离线 |
| Rerank（重排） | 本地 BGE-Rerank `BAAI/bge-reranker-base`，缺失时降级词重叠打分 | ✅ 可用 |

> ⚠️ `deepseek-embedding` / `deepseek-rerank` 是 DeepSeek 官方**不存在的模型名**，故未接入；硬接会导致上传文档向量化 404 失败。

---

## 二、本次修改清单

| 文件 | 变更内容 | 类型 |
|------|---------|------|
| `.env.example` | `EMBEDDING_BATCH_SIZE` 32 → 8；DeepSeek 配置段已含完整注释与「无 embedding/rerank」实测结论 | 配置 |
| `.env` | 同步 `EMBEDDING_BATCH_SIZE=8`（保留真实 key，未动） | 配置 |
| `docker-compose.yml` | 新增 `EMBEDDING_BATCH_SIZE`、`RERANKER_MODEL` 环境变量透传 | 配置 |
| `MODIFY_LIST.md` | 本文件 | 文档 |

---

## 三、核对确认项（已具备，本次未改动）

以下能力在此前已实现，本次逐一核对确认满足任务要求，故未重复修改：

1. **`config/settings.py` 读取全部 DeepSeek 环境变量**（已具备）
   - `DEEPSEEK_API_KEY` → `deepseek_api_key`
   - `DEEPSEEK_BASE_URL` → `deepseek_base_url`
   - `LLM_MODEL` → `llm_model`（默认 `deepseek-v4-flash`）
   - `LLM_TIMEOUT` → `llm_timeout`（默认 60.0）
   - `EMBEDDING_MODEL` → `embedding_model`（默认本地 BGE）
   - `EMBEDDING_BATCH_SIZE` → `embedding_batch_size`
   - `RERANK_MODEL` → `reranker_model`（默认本地 BGE-Rerank）

2. **key 为空启动警告**（已具备）
   - `Settings._resolve_llm_credentials` 校验器：`DEEPSEEK_API_KEY` 为空或仍为占位符时，启动打印明确 WARNING。

3. **LLM 调用统一走 DeepSeek、鉴权头正确、带超时**（已具备）
   - 全项目 LLM 统一走 `utils/llm_client.py` 的 `LLMClient`（`get_llm_client()` 单例）。
   - 使用 OpenAI SDK，自动携带 `Authorization: Bearer <key>`，超时取自 `settings.llm_timeout`（60s）。
   - 调用方：`rag_pipeline.answer()`、`agent_manager`、`planner/reflector/responder_node`、`doc_summary_tool` 均复用同一客户端。

4. **`docker-compose.yml` 加载 `.env` 的 DeepSeek 环境变量**（已具备 + 本次补充 batch/rerank）
   - 已透传 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `LLM_MODEL` / `LLM_TIMEOUT` 等，无硬编码 key。

---

## 四、本地操作步骤

```bash
# ① 复制配置，填入你自己的真实 DEEPSEEK_API_KEY
#    Linux/Mac:
cp .env.example .env
#    Windows:
#    copy .env.example .env
#    然后编辑 .env：DEEPSEEK_API_KEY=sk-你的真实key

# ② 删除旧向量持久化目录（旧向量为无密钥模拟生成，无效）
#    Linux/Mac:
rm -rf data/vector_store data/bm25_index
#    Windows:
#    rmdir /s /q data\vector_store
#    rmdir /s /q data\bm25_index

# ③ 重启后端
python -X utf8 -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# ④ 自测：上传一个简单 txt 文档，观察后端日志
```

### 自测日志预期

| 环节 | 应出现的日志 | 说明 |
|------|-------------|------|
| LLM 初始化 | `LLMClient 初始化完成: provider=deepseek, model=deepseek-v4-flash, base_url=https://api.deepseek.com` | LLM 走 DeepSeek ✅ |
| key 缺失告警 | `⚠️ LLM API Key 未配置（DEEPSEEK_API_KEY ...）` | 仅当 key 为空时出现 |
| 文本向量化 | `BGE 嵌入客户端初始化完成: model=BAAI/bge-small-zh-v1.5` | Embedding 走本地 BGE ✅ |

> 说明：由于 DeepSeek 官方无 embedding 接口，第 ④ 步日志中**不会**出现「调用 DeepSeek embedding」字样，取而代之的是本地 BGE 嵌入初始化日志——这是预期且正确的行为。

---

# 修改清单 — RAG 引擎优化（性能 + 召回率）

> 日期：2026-08-15
> 范围：仅修改 `ai/rag_engine/` + `config/settings.py` + `.env(.example)`，**上层 service / api / frontend 全部未动，对外接口入参返回值保持不变**。
> 硬性约束：原有「BM25 + 向量 → 加权融合 → BGE-Rerank」混合检索逻辑完整保留。

## 一、解决的三个问题

| 问题 | 根因 | 对策 |
|------|------|------|
| 向量化慢 | 全文一次性塞进单个 embedding 请求/前向 | 按 `EMBEDDING_BATCH_SIZE` 分批嵌入，向量库单批写入 |
| 问答时间长 | 每次提问都重跑改写+召回+重排 | 增加 TTL 检索结果缓存，重复提问直接命中 |
| 检索不到 | 重排候选数用了 `reranker_top_n`(默认5)，融合排序第6名及以后的相关 chunk 进不了重排即被丢弃 | 新增 `rerank_candidate_k`(默认20) 扩大重排候选 + query 改写多查询召回 |

## 二、改动清单

| 文件 | 改动 | 类型 |
|------|------|------|
| `config/settings.py` | 新增 9 个 RAG 优化配置项（见下表） | 配置 |
| `.env.example` / `.env` | 同步新增配置项 + 注释 | 配置 |
| `ai/rag_engine/retrieval_cache.py` | 新增 TTL 内存缓存（线程安全、LRU 淘汰） | 新增 |
| `ai/rag_engine/query_rewriter.py` | 新增 LLM query 改写（1~2 衍生查询，失败降级） | 新增 |
| `ai/rag_engine/chunker/base_chunker.py` | 新增 `normalize_chunk_text`（折叠空格/空行） | 修改 |
| `ai/rag_engine/chunker/semantic_chunker.py` | 分块归一化 + 过短块合并（避免语义被切碎） | 修改 |
| `ai/rag_engine/chunker/recursive_chunker.py` | 分块归一化 | 修改 |
| `ai/rag_engine/doc_version_manager.py` | embedding 按批调用 `_embed_batched` | 修改 |
| `ai/rag_engine/bm25_retriever/bm25_engine.py` | 入库后持久化 `save()` + 启动时 `load_all()` 恢复（修复重启后 BM25 召回为 0） | 修改 |
| `ai/rag_engine/hybrid_retriever.py` | 重排候选改 `rerank_candidate_k` + 调试日志 | 修改 |
| `ai/rag_engine/rag_pipeline.py` | 缓存 → 改写 → 多查询合并 → 图片召回 编排 | 修改 |
| `ai/rag_engine/vector_store/chroma_store.py` | `delete_by_document_id` 集合不存在时静默返回（消除告警噪声） | 修改 |
| `api/main.py` | `create_app()` 顶部调用 `setup_logging()`（修复日志从未初始化、RAG 调试日志丢失） | 修改 |

## 三、新增配置项（.env 可覆盖，无硬编码）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `RERANK_CANDIDATE_K` | 20 | 送入重排的候选条数（**必须 > RERANKER_TOP_N**） |
| `RAG_CACHE_ENABLED` | true | 检索结果缓存开关 |
| `RAG_CACHE_TTL` | 300 | 缓存过期时间（秒） |
| `RAG_CACHE_MAX_SIZE` | 512 | 缓存最大条目数 |
| `RAG_DEBUG_LOG` | false | 调试日志开关（打印改写/向量/BM25/rerank） |
| `QUERY_REWRITE_ENABLED` | true | query 改写开关 |
| `QUERY_REWRITE_COUNT` | 2 | 衍生查询个数（1~2） |
| `QUERY_REWRITE_TIMEOUT` | 10 | 改写 LLM 超时（秒） |
| `QUERY_REWRITE_MAX_TOKENS` | 1024 | 改写 LLM 最大输出 token（DeepSeek 推理模型需较大值，否则 content 为空） |
| `VECTOR_BATCH_SIZE` | 256 | 向量批量写入条数 |
| `MIN_CHUNK_SIZE` | 50 | 过短块合并阈值（字符数） |

> 已复用既有配置：`EMBEDDING_BATCH_SIZE`(8) 控制 embedding 分批大小。

## 四、接口超时保护说明

- 回答生成 LLM 调用：沿用 `LLM_TIMEOUT`（默认 60s，`utils/llm_client.py` 客户端级超时）。
- query 改写 LLM 调用：新增 `QUERY_REWRITE_TIMEOUT`（默认 10s），改写失败/超时自动降级回原问题，不阻塞主链路。

## 五、向后兼容

- `query_rewrite_enabled=false` 时，`retrieve()` 退化为单查询，行为与旧版完全一致。
- `rag_cache_enabled=false` 时，跳过缓存。
- 单查询时 `_merge_chunks` 为恒等操作，结果与旧版一致。
- 混合检索 `HybridRetriever.retrieve` 的 BM25/向量/融合/重排逻辑未改，仅新增 `rerank_candidate_k` 参数与候选数来源。

## 六、测试指引

```bash
# 1) 清空旧向量库与 BM25 索引（旧向量含旧分块策略，无效）
rm -rf data/vector_store data/bm25_index        # Linux/Mac
# Windows:
# rmdir /s /q data\vector_store
# rmdir /s /q data\bm25_index

# 2) 重启后端
python -X utf8 -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# 3) 重新上传 demo 文档（demo_docs/ 下 3 个 md + 1 个 txt）

# 4) 针对文档内知识点提问，验证召回正常
#    例：上传「RAG技术原理简介.md」后提问「什么是混合检索」

# 5) 重复提问同一个问题，验证缓存生效
#    第二次提问时后端日志出现「[RAG调试] 缓存命中」（需先开 RAG_DEBUG_LOG=true）
```

### 调试日志启用（排查召回失败）

在 `.env` 中设置 `RAG_DEBUG_LOG=true` 后重启，后端日志会打印：
- `[RAG调试] 原始query`
- `[RAG调试] query 改写: 原问题 -> [衍生1, 衍生2]`
- `[RAG调试] 向量召回 N 条` / `[RAG调试] BM25召回 N 条`
- `[RAG调试] 融合后 N 条` / `[RAG调试] 重排后结果`
- `[RAG调试] 缓存命中`

## 七、验证结果

### 单元测试（全绿）

- `python tests/test_step1_utils.py` → 11/11 通过
- `python tests/test_step3_rag.py` → 9/9 通过
- `python tests/test_step4_agent.py` → 通过
- `python tests/test_step5_services.py` → 6/6 通过
- `python tests/test_step6_api.py` → 6/6 通过

### 端到端自测（清空向量库 → 重传 demo 文档 → 提问验证）

| 验证点 | 结果 |
|--------|------|
| query 改写 | 生成 2 个衍生查询，与原问题一起去重检索 ✅ |
| BM25 召回 | 召回 13~18 条（修复前重启后为 0）✅ |
| 缓存命中 | 首次 14.96s → 命中后 4.38~4.82s ✅ |
| BM25 持久化 | 重启后端后日志「BM25 索引已从磁盘恢复 1 个集合」，召回正常 ✅ |
| 混合召回 | `vector=20, bm25=13, final=20`（融合+重排链路完整）✅ |

### 自测中追加修复的 3 个缺陷（超出 `ai/rag_engine` 字面范围，已如实记录）

1. **日志系统从未初始化**（`api/main.py`）：`setup_logging()` 从未被调用，根 logger 无 handler，INFO/DEBUG 日志全部丢失，导致 RAG 调试日志开关形同虚设。→ 在 `create_app()` 顶部补调用。
2. **query 改写输出为空**（`deepseek-v4-flash` 是推理模型）：`max_tokens` 过小时 `reasoning_content` 吃光 token、`content` 返回空。→ 新增 `QUERY_REWRITE_MAX_TOKENS=1024`，改写器显式传 `max_tokens`。
3. **BM25 索引不持久化**（`bm25_engine.py`）：入库后未落盘、重启后未加载，导致重启后 BM25 召回恒为 0。→ `index_chunks` 后 `save()`，`get_bm25_engine()` 首次创建时 `load_all()`。

> ⚠️ 第 1、3 项涉及 `api/main.py`、`ai/rag_engine/vector_store/chroma_store.py` 两个文件，属于「为保证调试日志功能可用」的最小必要改动；第 1 项 `api/main.py` 在任务约定范围（`ai/rag_engine`）之外，特此标注供确认。

---

# 修改清单 — 登录页面 UI 美化（适配试卷命题系统主题）

> 日期：2026-08-16
> 范围：仅前端 Streamlit 渲染展示层；后端登录鉴权、RBAC 权限、session 状态、登录/注册接口逻辑**完全未改动**。

## 一、动机

原登录页沿用「企业私有知识库智能助手」旧知识问答系统的 UI：深色渐变背景、`企` 字 logo、
「企业级 · 私有化 · RAG 检索增强生成平台」副标题，与「课程试卷智能命题校验批改系统」业务不匹配，
样式简陋、残留旧系统文字。

## 二、变更内容

| 文件 | 变更 | 类型 |
|------|------|------|
| `frontend/pages/auth_page.py` | 重写品牌区与页面样式：浅蓝灰教育风渐变背景、居中白色卡片、`卷` 字 logo、试卷系统标题/标语、系统能力简介小字 | 修改 |

## 三、UI 细节

| 项 | 说明 |
|----|------|
| 系统标题 | 课程试卷智能命题校验批改系统 |
| 副标题标语 | 基于多模态 RAG 的习题文档解析、智能命题、试卷校验与自动批改平台 |
| logo | `卷` 字（贴合试卷主题，替换旧 `企` 字） |
| 背景 | 浅蓝灰渐变（`#eef3fa → #dfe8f4`），清爽稳重，替换旧深色渐变 |
| 布局 | 居中卡片式，`max-width 640px`，适当留白，不铺满屏幕 |
| 输入框 | 用户名 + 密码（密码掩码），沿用全局输入框样式 |
| 登录按钮 | 主色蓝灰渐变按钮（沿用系统主色 `#3b5bdb`） |
| 系统简介小字 | 卡片底部能力标签：📄 PDF/Word 习题文档解析 · 🖼️ 多模态图片向量化 · 📝 自动生成试卷 · ✅ 校验批改试题 |
| 注册入口 | 保留「登 录 / 注 册」双标签页，注册页同步适配试卷主题 |

## 四、硬性约束落实情况

- ✅ **后端鉴权/RBAC 逻辑零改动**：`api.post("/api/v1/auth/login")`、`set_auth`、`st.session_state["nav_page"]="kb"`、`st.rerun` 等原有逻辑原样保留，仅改 `_brand_block` / `_AUTH_PAGE_CSS` / 新增 `_intro_block`。
- ✅ **去除旧系统残留**：登录页不再出现「企业私有知识库」「知识问答」「企」字 logo、「企业级 · 私有化 · RAG」等旧文案。
- ✅ **登录成功跳转原主页**：登录后仍跳转【课程库】页面，侧边栏及全部业务页面（课件管理、试卷中心、智能问答、Agent 任务、审计日志）未改动。
- ✅ **原有页面保留**：`chat_page.py` 等原有业务页面按需求「完全保留，不改动」。

## 五、测试要点

| # | 测试项 | 预期 |
|---|--------|------|
| 1 | 访问登录页 | 无「知识问答」字样；标题为「课程试卷智能命题校验批改系统」，标语贴合试卷命题业务 |
| 2 | 正确账号密码登录 | 正常登录，跳转原有【课程库】主页 |
| 3 | 错误账号密码登录 | 友好错误提示弹出（用户名/密码错误） |
| 4 | 登录后各功能页 | 课件上传、多模态向量化、命题生成试题等原有功能不受影响 |


---

# 修改清单 — 修复 docx（Word）文档处理流水线

> 日期：2026-08-16
> 范围：仅修复 `ai/rag_engine/document_parser/docx_parser.py` 一个文件；PDF 解析/分块/向量写入、多模态双后端、登录界面、试卷生成逻辑**完全未改动**。

## 一、问题根因

原 `docx_parser.py` 存在两处缺陷，导致「上传 docx 能提取图片、但正文与图片文本不分块、不入库」：

1. **未设置 `ParsedDocument.images` 字段**：`parse()` 返回时只填了 `pages`（正文文本），`images` 走 dataclass 默认值空列表 → 上层 `document_service._collect_images` 拿不到图片 → 图片不落盘、不做多模态向量化。
2. **未做图片 OCR**：图片内的文字（截图习题）从未被识别，更未参与文本分块。

而 PDF 之所以正常，是因为 `PDFParser.parse()` 同时完成三件事：正文文本进 `pages`、扫描页 OCR 文本进 `pages`、内嵌图进 `images`。docx 缺少后两条。

## 二、修复方案（完全对齐 PDF 三通道）

重写 `DocxParser.parse()`，产出与 PDF 一致的结构：

| 通道 | 实现 |
|------|------|
| 正文文本 | 按文档顺序遍历段落与表格，段落文本 + 表格行文本（`列1 | 列2 | ...`） |
| 图片提取 | 解析 docx zip 包 + rels 关系：遍历 body 的 `w:p`（段落）与 `w:tbl`（表格），递归查找 `a:blip[@r:embed]`（现代 DrawingML）与 `v:imagedata[@o:id]`（老式 VML），通过关系 id 从 `doc.part.rels` 取图片二进制与扩展名；按 rId 去重，段落内 + 表格内图片**不遗漏** |
| 图片 OCR | 每张图片调用 `PaddleOCR.recognize_image_bytes`，OCR 文本并入当前逻辑页文本，参与统一分块 |

关键设计：图片 OCR 文本直接写入 `parsed.pages[].text`（与正文一起），因此 `RagPipeline.ingest_document` 分块时**正文 + 图片 OCR 文本走完全相同的分块器（`SemanticChunker` / `RecursiveChunker`）、相同分块参数**，无需改动任何分块/向量写入代码。

## 三、流水线对齐（与 PDF 完全一致）

```
docx 上传 → 解析正文 + 提取全部内嵌图片二进制（docx_parser.parse）
        → 文本分块（正文 + 每张图片 OCR 文本，统一 SemanticChunker）
        → 图片落盘原图（document_service._collect_images → _save_image_bytes）
        → 图片预处理（过滤极小图/缩放/转 RGB）
        → 多模态图片向量化（local Chinese-CLIP / volcano 豆包，按当前 provider）
        → 文本向量 + 图片向量写入向量库
        → 异步任务完成，前端提示；部分图片失败仅告警
```

其中 `_collect_images`、`_preprocess_images`、`ingest_document`、`ingest_images` 均为既有通用逻辑，**未改动**，docx 与 PDF 复用同一条流水线。

## 四、异常隔离（硬性要求）

| 异常场景 | 处理 |
|----------|------|
| 单张图片二进制读取失败 / rels 关系缺失 | `_resolve_image` 捕获后跳过该图，记录 warning |
| 单张图片 OCR 失败（损坏图 / OCR 不可用） | `_ocr_image` try-except，OCR 文本为空，图片仍进 `images` 走多模态向量化 |
| 单张图片损坏（PIL 打不开） | 多模态预处理 `preprocess_image` 返回 `(False, msg)`，上层逐张 try-except 跳过 |
| 单张图片云端 API 报错（volcano） | `image_retriever.index_images` 逐张 try-except，跳过该图 |

**任一单张图片失败，绝不中断整个 docx 上传任务**：正文文本与其余图片照常分片入库，任务整体标记 `ready`，仅输出警告。

## 五、`ENABLE_IMAGE_EMBED=false` 行为

总开关关闭时，`document_service._process_document` 跳过 `_collect_images` / `_preprocess_images` / `ingest_images`，docx 只走「解析正文 → 文本分块 → 文本向量化」纯文本链路，图片处理全部跳过（本 parser 的图片提取虽仍执行但不会被落盘/向量化，OCR 在解析阶段仍会执行——与 PDF 扫描页 OCR 行为一致，不产生额外外部调用）。

## 六、变更清单

| 文件 | 变更内容 | 类型 |
|------|---------|------|
| `ai/rag_engine/document_parser/docx_parser.py` | 重写 `parse()`：新增图片提取（zip+rels）、图片 OCR 并入文本分块、`images` 字段填充、逻辑页顺序扫描 | 修改 |

> 其余文件（PDF 解析、分块器、document_service、rag_pipeline、image_retriever、多模态客户端等）**零改动**。

---

# 修改清单 — 重写优化项目 README

> 日期：2026-08-16

## 变更内容

| 文件 | 变更内容 | 类型 |
|------|---------|------|
| `README.md` | 在旧版基础上迭代重写：继承原项目简介/架构/业务流程/目录结构/部署/测试等合理内容，补齐「项目亮点、功能模块列表、截图占位区、完整 .env 示例、使用说明、注意事项、未来优化方向」；按实际实现修正多模态后端切换描述（改为 `.env` 配置 + 重启，删除「运行时切换/系统设置页」等未实现能力） | 修改 |

## 关键修正说明

- 如实描述多模态后端切换：`IMAGE_EMBED_PROVIDER`（local/doubao）与 `ENABLE_IMAGE_EMBED` 总开关均通过 `.env` 配置、启动时读取，**需重启后端生效**；不编写「前端无需重启切换」「系统设置页」等当前未实现的功能。
- 明确密钥安全提示：`.env` 不入库，仓库仅保留 `.env.example` 占位模板。
- 补充 docx/PDF 内嵌习题图片解析、强容错上传流水线、双可插拔多模态后端、RBAC 权限、LangGraph 双 Agent 等真实特性说明。
- 新增「未来优化方向」，将「多模态后端运行时热切换」列为待实现项。

---

# 修改清单 — 三大痛点工程优化（性能 / 进度 / 内存 / OCR 健壮性）

> 日期：2026-08-16
> 范围：仅做性能与健壮性增强，原有全部业务逻辑（PDF/docx 解析、分片、双后端多模态、命题批改、RBAC、异步任务）完整保留，未改业务流程。

## 一、OCR 多进程并发（提升大批量图片处理速度）

> 关键发现：PaddleOCR 底层是 C++ 预测器（PaddleX），**非线程安全**——单进程内多线程并发调用
> 同一实例 `predict()` 会触发 `invalid vector<bool> subscript` 并**段错误**（实测后端崩溃）。
> 因此放弃 ThreadPoolExecutor 多线程，改为**多进程并发**（每个子进程独立 PaddleOCR 实例，进程间隔离）。

- `utils/ocr_pool.py`（新增）：常驻 `ProcessPoolExecutor` 进程池，惰性创建、跨多次上传复用（避免每次重新加载模型）；每个 worker 子进程通过 initializer 独立加载 PaddleOCR；单张失败仅返回空串；进程池创建失败 / 执行异常 → **自动降级串行 OCR**（不崩溃）。
- 进程数钳制：`min(settings.ocr_concurrency, 4, 图片数)`，默认 4，硬上限 4（进程比线程更耗内存，避免内存爆炸）。
- `ai/rag_engine/document_parser/docx_parser.py`：`_scan_to_pages_and_images` 重构为「先收集全部内容单元 → 图片进程池并发 OCR → 按文档顺序组装逻辑页」，分页/分块语义与串行版**完全一致**；`_ocr_images_concurrent` 委托 `utils.ocr_pool.ocr_images_concurrent`。
- `utils/ocr_engine.py`：`PaddleOCREngine` 增加 `_predict_lock` 串行化 `predict()`（防御性：串行降级路径与任何并发调用都不会段错误）。

## 二、documents 表新增 progress_detail + 前端 OCR 细粒度进度

- `db/models.py`：`Document` 新增 `progress_detail`（JSON）字段。
- `db/crud/document_crud.py`：新增 `update_progress`。
- `scripts/migrate_course.py`：新增 `add_document_progress_column`（幂等，SQLite=TEXT / PG=JSON）。
- `services/document_service.py`：`_process_document` 各阶段上报 `progress_detail`；OCR 阶段由 `_report_ocr_progress` 自开独立 session 写入 `{stage:'ocr', done, total}`（进度回调在主进程触发，避免跨进程/线程 session 竞争）。
- `ai/rag_engine/document_parser/parser_factory.py`：`parse_document` 增加可选 `progress_callback`（仅 DocxParser 使用，PDF/MD/TXT/图片忽略）。
- `frontend/pages/document_page.py`：轮询读取 `progress_detail`，`stage=='ocr'` 时展示 `OCR文字识别中：done / total 张`。

## 三、本地 Chinese-CLIP 内存回收（缓解 OOM）

- `utils/multimodal_embedding_client.py`：`embed_images` / `embed_texts` 增加 `try/finally` 释放——`del` 中间 tensor、关闭 PIL 图像对象、`gc.collect()`；图片读取改用 `with Image.open()` 及时关闭文件句柄。
- 新增 `_release_memory`：每次推理 `gc.collect()`，每 `clip_gc_interval`（默认 10）张做一次完整回收（含 `torch.cuda.empty_cache()`）。
- 模型加载逻辑维持懒加载不变，**未做 ONNX 量化**（写入 README 未来优化方向）。

## 四、修复 OCR 初始化失败永久僵死（指数退避重试 + 前端告警）

- `utils/ocr_engine.py`：删除 `_init_failed` 一次性禁用逻辑；改为 `_init_fail_count` / `_init_failed_at` / `_init_fail_reason` 三态 + 指数退避（`ocr_retry_interval` 基础 60s，`base * 2^(n-1)`，封顶 960s）。
- 退避期内直接返回 None（不反复初始化刷日志）；到期自动重试，临时故障恢复后**无需重启服务**即可重新使用 OCR。
- 新增 `get_ocr_failure_reason()`；`document_service._ocr_failure_reason` 将失败原因写入前端任务警告（而非静默跳过）。

## 五、配置新增（.env 可覆盖，带注释）

| 配置 | 默认 | 说明 |
|------|------|------|
| `OCR_CONCURRENCY` | 4 | docx 大量图片并发 OCR 进程数（进程池，最终钳制 1~4） |
| `OCR_RETRY_INTERVAL` | 60 | OCR 初始化失败后指数退避基础间隔（秒） |
| `CLIP_GC_INTERVAL` | 10 | 本地 CLIP 每处理 N 张图做一次完整内存回收 |

## 六、变更清单

| 文件 | 变更 | 类型 |
|------|------|------|
| `utils/ocr_pool.py` | 新增：常驻进程池并发 OCR（含串行降级） | 新增 |
| `utils/ocr_engine.py` | predict 加锁串行 + 指数退避重试 + 失败原因记录 | 修改 |
| `ai/rag_engine/document_parser/docx_parser.py` | 图片 OCR 进程池并发化 + 进度回调 | 修改 |
| `ai/rag_engine/document_parser/parser_factory.py` | `parse_document` 增加 progress_callback | 修改 |
| `db/models.py` | Document 新增 progress_detail 字段 | 修改 |
| `db/crud/document_crud.py` | 新增 update_progress | 修改 |
| `scripts/migrate_course.py` | 新增 progress_detail 列迁移 | 修改 |
| `services/document_service.py` | 细粒度进度上报 + OCR 失败告警 | 修改 |
| `frontend/pages/document_page.py` | 前端展示 OCR 进度 x/总数 | 修改 |
| `utils/multimodal_embedding_client.py` | 本地 CLIP 内存回收（del/gc/分批） | 修改 |
| `config/settings.py` | 新增 ocr_concurrency / ocr_retry_interval / clip_gc_interval | 修改 |
| `.env.example` | 新增 3 项配置（带注释） | 修改 |

---

# 上层业务迭代：题目去重与知识点均衡 · 试卷编辑 · 精细化溯源批改

> 日期：2026-08-16
> 范围：在现有稳定底模（多模态 RAG / 文档解析 / 双 Agent 出卷 / 批改 Agent / RBAC / 异步任务）之上，**只新增上层试卷业务逻辑**。
> 硬性约束遵守：底层 RAG、文档解析、多模态双后端、异步任务、鉴权、数据库旧字段、原有接口入参出参**全部保留未动**；不重构双 Agent 链路、不新建大模型调用链路（去重/均衡为纯规则，单题重出复用双 Agent 图，批改升级复用批改 Agent）。
> 数据库**未新增任何字段**（标签云/雷达图由 questions 实时计算，批改明细写入已有 grading_details JSON 列）。

## 一、校验 Agent 新增第 5 组校验：题目相似度去重 + 知识点均衡检测

- `ai/agent_langgraph/exam/validator_node.py`：
  - 新增纯 Python「文本向量相似度」：字符 2-gram 计数向量余弦（`_char_ngrams` / `_vector_cosine` / `_text_similarity`），**零外部依赖**（不引入 sklearn，兼容全新环境）。
  - 新增 `_cross_question_checks(questions, dup_threshold, max_ratio)` 跨题校验：
    - **5.1 题目相似度去重**：两两对比「题干+知识点」相似度，≥ `EXAM_DUP_SIMILARITY_THRESHOLD` 判重复，保留先出现题、判后出现题 fail，回传命题 Agent 重出。
    - **5.2 知识点均衡检测**：统计每题 knowledge_point（生成时已基于 RAG 课件原文、并经 4 项校验验证存在），单一知识点占比 > `EXAM_KNOWLEDGE_MAX_RATIO` 判定偏科，把超出上限的题判 fail 换考点重出。
  - 在 `validator_node` 逐题 4 项校验之后追加执行；判定结果写入 `validation_results`（带 `rule: dedup/balance` 供前端轨迹展示）+ `rejected_questions`（带 reject_reason 回传命题 Agent）。
  - **不改图拓扑**：仍为 generator → validator → 条件边重生成，仅在同一校验节点内追加跨题检查。

## 二、试卷页面新增知识点标签云 + 覆盖率雷达图

- `frontend/pages/exam_page.py`：`_render_knowledge_vis` / `_knowledge_stats` / `_tag_cloud_html` / `_radar_svg`。
  - **标签云**：HTML 圆角胶囊，字号/颜色随知识点出现次数变化。
  - **覆盖率雷达图**：纯 SVG 多边形（top6 知识点 + 其他），展示整套试卷考点分布均衡情况。
  - 数据来自试卷 `questions[].knowledge_point`，前端实时计算，**无需后端改动、无新依赖**（无 plotly/matplotlib/wordcloud）。

## 三、试卷编辑模式：单题重出、增删改试题

- `ai/agent_langgraph/exam/exam_manager.py`：新增 `regenerate_question(kb_id, question, difficulty)` —— 以该题为「不合格题」喂入**现有双 Agent 图**（命题 Agent 换考点重出 → 校验 Agent 自动复核，max_iterate=1），复用原有节点，不新建 LLM 链路。
- `services/exam_service.py`：
  - 新增 `regenerate_question(db, user_id, paper_id, qid)`（admin+），重出结果实时落库并审计。
  - 增强 `update`：提交 questions 时自动 `_sanitize_questions`（过滤无效题、重排 qid、校验选择题选项），并**自动重算 reference_answers / total_score / question_config**——编辑后标签云、雷达图数据自动一致。
  - 新增 `_sanitize_questions` 静态方法。
- `db/schemas.py`：`ExamPaperUpdate` 增加 `total_score` / `question_config` 可选字段（服务端重算覆盖）。
- `api/router/exam_router.py`：新增 `POST /papers/{paper_id}/regenerate/{qid}`。
- `frontend/pages/exam_page.py`：`_render_editor` / `_save_paper`——编辑模式开关（owner/admin 可见，read 学生隐藏），每题操作：**单题重出 / 编辑（题干/选项/答案/知识点/分值）/ 删除**，底部**新增自定义试题**；所有操作走现有 `PUT /papers/{id}`（ExamPaperUpdate）或重出端点，实时写入数据库，`st.rerun()` 后标签云/雷达图自动刷新。

## 四、客观题错误解析 + 溯源

- `ai/agent_langgraph/exam/grader.py`：新增 `grade_objective_detail(kb_id, question, student_answer, score)` —— 仅对**答错**的客观题（单选/填空）调用批改 Agent 生成「错误解析」：说明为什么错、本题考察知识点、课件溯源片段（题目自带 source_refs 优先，缺失则 RAG 检索；LLM 引用做逐字锚定防幻觉）。
- `services/exam_service.py`：`submit_answer` 统一改走后台批改任务（全客观题试卷也异步），`_grade_task` 对答错客观题追加 `analysis` / `knowledge_point` / `source_refs` 写入 `grading_details`（复用已有 JSON 列，无新增字段）。
- `frontend/pages/exam_page.py`：批改详情展示「❌ 错误解析 / 🎯 考察知识点 / 📖 课件原文溯源」。

## 五、主观题四维度分项打分 + 分项溯源批改

- `ai/agent_langgraph/exam/grader.py`：`grade_subjective` 升级为四维度分项：
  - ① 知识点匹配度 ② 答题步骤完整性 ③ 结论答案正确性 ④ 语言表述规范性；
  - 权重从 `.env` 读取并自动归一化（`_subjective_weights`，兼容 30/30/20/20 与 0.3/0.3/0.2/0.2）；满分按权重拆分（`_dimension_maxes`，余数按小数部分分配，保证各维满分之和=总分）。
  - 每个维度独立 `score / max_score / comment / source_refs`（逐字锚定防幻觉）；返回结构新增 `dimensions`，同时保留 `score / strengths / missing / source_refs` 兼容旧消费方。
- `services/exam_service.py`：`_grade_task` 将 `dimensions` 写入 `grading_details`。
- `frontend/pages/exam_page.py`：批改详情展示「📐 四维度分项打分」——每维度得分、分项点评、各维度课件溯源原文。

## 六、配置新增（.env 可覆盖，带注释）

| 配置 | 默认 | 说明 |
|------|------|------|
| `EXAM_DUP_SIMILARITY_THRESHOLD` | 0.9 | 题目相似度去重阈值（文本向量相似度 0~1，达到即判重复并自动重出） |
| `EXAM_KNOWLEDGE_MAX_RATIO` | 0.5 | 单一知识点题数占比上限，超过判定偏科并自动重出 |
| `EXAM_GRADE_WEIGHT_KNOWLEDGE` | 0.3 | 主观题分项权重：知识点匹配度 |
| `EXAM_GRADE_WEIGHT_STEPS` | 0.3 | 主观题分项权重：答题步骤完整性 |
| `EXAM_GRADE_WEIGHT_CONCLUSION` | 0.2 | 主观题分项权重：结论答案正确性 |
| `EXAM_GRADE_WEIGHT_LANGUAGE` | 0.2 | 主观题分项权重：语言表述规范性 |

## 七、变更清单

| 文件 | 变更 | 类型 |
|------|------|------|
| `ai/agent_langgraph/exam/validator_node.py` | 新增第 5 组校验（去重 + 知识点均衡，纯 Python 文本向量相似度） | 修改 |
| `ai/agent_langgraph/exam/exam_manager.py` | 新增 `regenerate_question`（复用双 Agent 图） | 修改 |
| `ai/agent_langgraph/exam/grader.py` | 主观题四维度分项打分 + 客观题错误解析 | 修改 |
| `services/exam_service.py` | 单题重出 / 编辑自动重算 / 提交统一后台批改 / 客观题错误解析落库 | 修改 |
| `db/schemas.py` | `ExamPaperUpdate` 增加 total_score / question_config | 修改 |
| `api/router/exam_router.py` | 新增 `POST /papers/{id}/regenerate/{qid}` | 修改 |
| `config/settings.py` | 新增 6 项配置（去重阈值/知识点占比/四维度权重） | 修改 |
| `.env.example` | 新增 6 项配置（带注释） | 修改 |
| `frontend/pages/exam_page.py` | 知识点标签云 + 雷达图 + 编辑模式 + 分项批改展示 | 修改 |

> 数据库零新增字段；底层 RAG / 文档解析 / 多模态双后端 / 异步任务 / 鉴权 / 旧接口完全未动。
