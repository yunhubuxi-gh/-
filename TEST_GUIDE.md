# docx（Word）文档处理测试指南

> 日期：2026-08-16
> 范围：验证修复后的 docx 文档完整处理流水线（正文 + 图片提取 + 图片 OCR 统一分片 + 图片多模态向量化）。
> 前置：后端已完成迁移与依赖安装；测试账号 `admin / Teacher@123`（owner，可上传）。

## 环境准备

```bash
# 1) 迁移（幂等）
python scripts/migrate_course.py

# 2) 启动后端
python -X utf8 -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# 3) 启动前端
python -X utf8 -m streamlit run frontend/app.py --server.port 8501
```

- 教师账号：`admin / Teacher@123`（owner 权限，可上传/出卷）
- `.env` 关键开关：`ENABLE_IMAGE_EMBED`（图片向量化总开关）、`IMAGE_EMBED_PROVIDER`（`local` / `volcano`）

---

## 测试用例 1 — 含多图 docx：正文分块 + 图片 OCR 文本入库 + 图片向量化

**目的**：验证 docx 修复后走完整流水线——正文与图片 OCR 文本统一分块入库，图片同时产生多模态向量；上传成功。

**步骤**：
1. `.env` 设 `ENABLE_IMAGE_EMBED=true`，重启后端。
2. 准备一个含多张内嵌图片（如数学公式/习题截图，图片内文字清晰）的 docx，正文放若干段落 + 一个表格（表格内含文字与图片）。
3. 前端「文档管理」→ 选择课程库 → 上传该 docx。
4. 观察进度条依次经过：`解析文件 → 提取页面图片 → OCR文字识别 → 文本分块&文本向量化 → 图片预处理 → 图片多模态Embedding向量化 → 写入向量库完成`。
5. 完成后文档状态为「就绪」，无警告。

**后端日志预期**：
```
DOCX 解析完成: 提取到 N 张内嵌图片, pages=M, chars=...
```

**通过标准**：
- 文档最终 `ready`（非 `failed`）。
- 正文文本 + 每张图片的 OCR 文字**都**进入向量库（可用图片内文字提问命中，例如图片里写「二次函数顶点公式」，检索「二次函数顶点」能命中该文档）。
- 表格内文字与表格内图片均被提取，不遗漏。
- 图片产生 CLIP/豆包 多模态向量（图片检索分支可召回）。

---

## 测试用例 2 — docx 含损坏图片：整体成功，仅跳过该图

**目的**：验证异常隔离铁则——单张图片损坏/OCR 失败不导致 docx 上传任务失败。

**步骤**：
1. `.env` 设 `ENABLE_IMAGE_EMBED=true`。
2. 准备一个 docx：正文正常 + 1 张损坏图片（人为破坏图片字节，使 PIL 无法解码）+ 1 张正常图片。
3. 上传该 docx。
4. 观察文档状态与前端提示。

**后端日志预期**：
```
DOCX 解析完成: 提取到 2 张内嵌图片, ...   ← 损坏图仍被提取
docx 图片 OCR 失败（跳过该图 OCR，不影响整体）: ...   ← 损坏图 OCR 优雅降级
[图片向量化] 图片 page_x_img_y 失败: <原因>   ← 仅损坏图预处理/向量化失败
[图片向量化] 成功 1 张，失败 1 张，文本内容已正常入库
```

**通过标准**：
- 文档最终 `ready`（非 `failed`）。
- 正文文本 + 正常图片的 OCR 文本照常入库。
- 仅损坏图被跳过，其余图片向量 + 文本向量全部完成。
- 前端展示 ⚠️ 警告而非报错。

---

## 测试用例 3 — 切换多模态后端（local ↔ volcano）

**目的**：验证 docx 图片向量化在两套后端间可无缝切换，切换后 docx 上传仍正常。

**步骤**：
1. 切换 A：`.env` 设 `IMAGE_EMBED_PROVIDER=local`（Chinese-CLIP），重启后端，上传含图 docx，确认成功。
2. 切换 B：`.env` 设 `IMAGE_EMBED_PROVIDER=volcano`（豆包 `doubao-embedding-vision-251215`，Agent Plan 专属地址），重启后端，上传同一 docx，确认成功。

**后端日志预期**（volcano）：
```
[图片向量化] 使用豆包多模态 Embedding（dim=...）
```

**通过标准**：
- 两种 provider 下 docx 上传均 `ready`，正文/图片 OCR 分块不受影响。
- 图片向量维度隔离正确（`local` 768 维 / `volcano` 1024 或 2048 维，分别落到 `kb_{id}_img_{dim}` 集合，互不冲突）。
- 豆包 key/地址均从 `.env` 读取，无硬编码。

---

## 测试用例 4 — `ENABLE_IMAGE_EMBED=false`：跳过图片处理，文本正常分块入库

**目的**：验证关闭开关后 docx 只走文本链路，不做图片落盘/向量化，正文 + 图片 OCR 文本仍正常分块入库。

**步骤**：
1. `.env` 设 `ENABLE_IMAGE_EMBED=false`，重启后端。
2. 上传含图 docx。
3. 观察进度条**无**「图片预处理 / 图片多模态Embedding向量化」子状态。
4. 完成后文档 `ready`。

**后端日志预期**：无 `image_preprocess` / `image_embedding` / `[图片向量化]` 相关日志。

**通过标准**：
- 文档最终 `ready`，无图片向量化日志。
- 正文文本正常分块入库，文本检索可命中。
- 启动不报错（即使 `torch/transformers/modelscope` 未安装）。

---

## 测试用例 5 — PDF 回归：原流程不受影响

**目的**：验证本次仅改 docx 解析器，PDF 解析/分块/向量写入完全不受影响。

**步骤**：
1. `.env` 设 `ENABLE_IMAGE_EMBED=true`。
2. 上传一个含图 PDF（原生 + 扫描均可）。
3. 观察 PDF 仍走原有完整流程：`解析文件 → 提取页面图片 → OCR文字识别 → 文本分块&文本向量化 → 图片预处理 → 图片多模态Embedding向量化 → 写入向量库完成`。
4. 完成后文档 `ready`。

**通过标准**：
- PDF 行为与此前完全一致，无回归。
- 底层 `pdf_parser.py` / 分块器 / `document_service` / `rag_pipeline` 未被改动（可用 `git diff` 确认本次仅 `ai/rag_engine/document_parser/docx_parser.py` 变更）。

---

## 回归验证（原有业务不破坏）

```bash
python tests/test_step1_utils.py     # 工具/配置
python tests/test_step2_db.py        # 数据模型
python tests/test_step3_rag.py       # RAG（BM25+向量+rerank，未动）
python tests/test_step5_services.py  # 服务层
python tests/test_step6_api.py       # API
```

**通过标准**：全部绿灯；本次仅 docx 解析器变更，底层未动，测试结果与此前一致。
