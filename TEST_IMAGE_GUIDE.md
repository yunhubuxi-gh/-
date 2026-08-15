# 图片多模态向量化（Chinese-CLIP）测试指南

> 日期：2026-08-15
> 前置：已完成 `python scripts/migrate_course.py`（补 `documents.processing_warning` 列），
> 后端依赖按需安装：`pip install torch transformers modelscope pillow`（仅当 `ENABLE_IMAGE_EMBED=true` 需要）。

## 环境准备

```bash
# 1) 迁移（补列，幂等）
python scripts/migrate_course.py

# 2) 启动后端（当前在后台任务运行中）
python -X utf8 -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# 3) 启动前端
python -X utf8 -m streamlit run frontend/app.py --server.port 8501
```

- 教师账号：`admin / Teacher@123`（owner 权限，可上传/出卷）
- 学生账号：`demo / Student@123`、`stu2 / Student@123`（read 权限）

> ⚠️ 首次开启 `ENABLE_IMAGE_EMBED=true` 时，Chinese-CLIP 模型（约 1.2GB）会在**首次处理图片时**从 modelscope 下载到本地缓存，请耐心等待；下载进度会打印在后端日志。

---

## 测试用例 1 — 含多图 PDF：细粒度子状态 + 部分损坏不失败

**目的**：验证①PDF 单页多图逐张处理；②上传任务走过 7 段子状态；③某张图损坏/异常时任务整体仍 `ready` 并带警告。

**步骤**：
1. 准备一个含多张内嵌图片的 PDF（`demo_docs/` 下可自建，或任意含图 PDF），其中可人为放置 1 张超小图（<32px）或损坏图片以触发「单张跳过」。
2. `.env` 设 `ENABLE_IMAGE_EMBED=true`，重启后端。
3. 前端「文档管理」→ 选择课程库 → 上传该 PDF。
4. 观察上传进度条依次经过：`解析文件 → 提取页面图片 → OCR文字识别 → 文本分块&文本向量化 → 图片预处理 → 图片多模态Embedding向量化 → 写入向量库完成`。
5. 完成后观察：文档状态为「就绪」；若存在失败图片，页面顶部出现 ⚠️ 警告「部分图片向量化失败（共 N 张），文本内容已正常入库。详情：…」。

**后端日志预期**：
```
[图片向量化] 开始预处理 N 张图片
[图片向量化] 图片 page_3_img_2 失败: <原因>   ← 只跳过这一张
[图片向量化] 成功 M 张，失败 K 张，文本内容已正常入库
```

**通过标准**：
- 文档最终 `ready`（非 `failed`）。
- 单张异常未导致任务失败，其余图片向量 + 文本向量全部完成。
- 前端展示警告而非报错。

---

## 测试用例 2 — 单独 jpg/png 图片：文字描述提问召回 + 前端渲染

**目的**：验证直接上传图片时「原图保存 + OCR 文本 chunk + CLIP 向量」完整链路，及图片检索分支能在问答中渲染图片。

**步骤**：
1. `.env` 设 `ENABLE_IMAGE_EMBED=true`。
2. 上传一张内容明确的图片（如一张写有「机器学习分类流程」的示意图 / 或含明显物体的图）到课程库。
3. 在「智能问答」页选择该课程库，用**文字描述**提问（不直接说图片文件名，例如「帮我找一下关于机器学习分类流程的图」或描述图中物体）。
4. 观察回答下方引用卡片是否渲染出该图片（`content_type=image` 的片段显示为图片缩略图）。

**后端日志预期**：
```
[RAG调试] 图片检索召回 K 张（CLIP）
```

**通过标准**：
- 检索结果中出现 `content_type=image`、带 `image_path` 的条目，且与文本 chunk 合并去重。
- 前端渲染出对应图片。
- 图片本身也产生了 OCR 文本 chunk，可被文本检索命中（双通道）。

---

## 测试用例 3 — `ENABLE_IMAGE_EMBED=false` 完全回退、无报错

**目的**：验证关闭开关时走旧逻辑，不加载 CLIP、不执行图片向量、不导入 CLIP 库，缺依赖也不报错。

**步骤**：
1. `.env` 设 `ENABLE_IMAGE_EMBED=false`（保持 `torch/transformers/modelscope` 不装或已装均可）。
2. 重启后端，观察启动日志**无**任何 CLIP / torch / modelscope 相关加载日志。
3. 上传一个含图 PDF 和一张 jpg 图片，观察走「解析 → 提取页面图片 → OCR → 文本向量化 → 就绪」，**无** `image_preprocess` / `image_embedding` 子状态。
4. 上传任务正常完成，文档 `ready`。
5. 提问验证文本 RAG 正常（BM25+向量+rerank 链路不受影响）。

**通过标准**：
- 启动不报错（即使 `torch/transformers/modelscope` 完全未安装）。
- 无图片向量相关日志/子状态。
- 文本文档摄入、检索、问答全部正常。

---

## 测试用例 4 — 模拟模型下载失败：服务不崩溃、图片功能自动关闭、文本正常

**目的**：验证 CLIP 懒加载 + 下载失败时优雅降级。

**步骤**（模拟下载失败，任选一种）：
1. **断网/改域名**：临时将 `.env` 的 `CLIP_MODEL_NAME` 改成一个不存在的模型 id（如 `damo/not-exist-clip-xxx`），或断网。
2. `.env` 设 `ENABLE_IMAGE_EMBED=true`，`CLIP_DOWNLOAD_RETRY=1`（减少等待）。
3. 重启后端，上传一张图片 / 含图 PDF。
4. 观察后端日志出现模型下载/加载失败告警，系统捕获异常后**关闭图片向量化**。
5. 观察文档仍在「文本链路」正常摄入 → `ready`（可能带「图片向量化失败」警告，或无警告直接跳过图片分支）。
6. 随后提问验证文本 RAG 正常。

**后端日志预期**：
```
⚠️ 图片向量化客户端初始化失败: <原因>，已关闭图片向量化，系统继续文本业务
```

**通过标准**：
- 服务**不崩溃**，进程保持运行。
- 图片功能自动关闭，文本上传/检索/问答全部正常。
- 上传任务不被标记为失败（文档 `ready` 或带警告 `ready`）。

---

## 回归验证（原有业务不破坏）

```bash
python tests/test_step1_utils.py     # 工具/配置
python tests/test_step2_db.py        # 数据模型（含 processing_warning 迁移）
python tests/test_step3_rag.py       # RAG（BM25+向量+rerank，未动）
python tests/test_step5_services.py  # 服务层
python tests/test_step6_api.py       # API
```

**通过标准**：全部绿灯；`ENABLE_IMAGE_EMBED=false` 时测试结果与此前一致（底层未动）。

---

## 附：常用调试开关

| 配置 | 作用 |
|------|------|
| `RAG_DEBUG_LOG=true` | 打印图片检索召回、向量/BM25/rerank 各阶段日志 |
| `CLIP_DEVICE=cpu` | 强制 CPU（无 GPU 环境，日志提示「CPU 运行图片向量化速度较慢」） |
| `CLIP_MAX_IMAGE_SIDE=336` | 图片预处理最大边长（放大/缩小到 336） |
| `CLIP_MIN_IMAGE_SIDE=32` | 过滤掉短边小于此值的极小图 |
