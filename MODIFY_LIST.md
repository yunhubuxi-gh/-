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
