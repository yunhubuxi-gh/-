# 项目自检核对清单

本文档逐条核验项目开发过程中约定的一系列「铁则」，供交付前自查与答辩讲解使用。
标注 ✅ 为已核验通过。

---

## 一、存储边界约束（三者分离）

| 检查项 | 结果 | 说明 |
|--------|------|------|
| PostgreSQL 只存业务元数据，不存 embedding 向量 | ✅ | `db/models.py` 无 embedding/chunk 正文字段，仅 `vector_collection` 名称等元数据 |
| 不存 chunk 分块文本 | ✅ | chunk 文本存向量库（`rag_pipeline.ingest_document` → `version_manager.index_chunks`） |
| 不存文档原始二进制 | ✅ | 原始文档存文件系统，`documents.file_path` 记录路径（`document_service.upload` 落盘） |
| 密码只存 bcrypt 哈希，禁止明文 | ✅ | `utils/security.hash_password`；`user_crud.create` 用 `password_hash` |
| 长期记忆不写 PG，存文件系统 | ✅ | `long_term_memory.py` JSON 持久化到 `AGENT_LONG_TERM_DIR` |

**关键代码位置**：
- `db/models.py`：9 张表均无向量/正文字段
- `ai/rag_engine/rag_pipeline.py`：`ingest_document`（chunk+向量写向量库）
- `services/document_service.py`：`upload`（文件落盘 + 元数据入库）

---

## 二、service 层权限拦截（四级 RBAC）

| 检查项 | 结果 | 说明 |
|--------|------|------|
| owner 全权限 | ✅ | `utils/permission.py` 权限等级 owner=100 |
| admin 管理成员/改配置 | ✅ | `kb_service.update` 校验 `ADMIN`；成员增删改校验 `ADMIN` |
| write 上传/编辑文档 | ✅ | `document_service.upload/update_title/delete/reindex` 校验 `WRITE` |
| read 只读问答检索 | ✅ | `chat_service.ask`、`document_service.list/get` 校验 `READ` |
| 越权抛统一业务异常 | ✅ | `PermissionException(KB_NO_PERMISSION)`，并写审计 `permission_denied` |

**关键代码位置**：
- `services/kb_service.py`：`_check_permission`
- `services/document_service.py`：`_check_permission`
- `services/chat_service.py`：`_check_read`
- `utils/permission.py`：`has_permission` / 四级等级映射

---

## 三、审计日志入口收敛

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 业务层审计统一走 services.write_audit_log | ✅ | `services/__init__.py` 提供统一入口 |
| 文件审计走 utils.logger.log_audit | ✅ | `write_audit_log` 内部调用 |
| 数据库审计走 audit_log_crud | ✅ | `write_audit_log` 内部调用 |
| API 层不直接写审计日志 | ✅ | 已核验 `api/` 无 `log_audit` 调用 |
| Agent 日志复用 utils.audit_log，不自建 | ✅ | `agent_manager._audit` 调 `log_audit` + `audit_log_crud` |

**关键代码位置**：
- `services/__init__.py`：`write_audit_log`
- `ai/agent_langgraph/agent_manager.py`：`_audit`

---

## 四、全局异常处理

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 业务异常统一捕获 | ✅ | `api/handlers.py` 捕获 `AppException` 及子类 |
| 返回标准格式 `{code, message, data, timestamp}` | ✅ | 复用 `utils/response.fail_response` |
| 参数校验异常 → 422 | ✅ | `RequestValidationError` 处理器 |
| 系统异常 → 500 | ✅ | 通用 `Exception` 处理器 |
| service 层不做 HTTP 响应封装 | ✅ | service 只抛异常，不 import response |

**关键代码位置**：`api/handlers.py`（4 个异常处理器）

---

## 五、无硬编码配置

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 数据库连接串读 config/.env | ✅ | `config/settings.py` `database_url` |
| JWT 密钥读 config/.env | ✅ | `settings.jwt_secret_key`（.env 中，已 gitignore） |
| LLM/嵌入模型密钥读 config/.env | ✅ | `settings.llm_api_key` 等 |
| 文件/向量库/日志路径读 config | ✅ | `settings.upload_dir` 等，可 .env 覆盖 |
| Agent 记忆路径读 config | ✅ | `agent_config.get_agent_config().long_term_dir` |
| 重试次数/记忆窗口读 config | ✅ | `agent_config` + `settings.agent_*` |
| 前端 API base_url 读 config | ✅ | `frontend/config.py` 从 settings 派生 |
| 硬编码密钥/token 扫描 | ✅ | 仅 `db/init_db.py` 演示账号密码（需求要求的初始化账号，README 有安全提示） |

**已扫描确认**：源码中无硬编码 `sk-*` 密钥、无硬编码绝对路径；所有地址/端口/路径均为 config 层可覆盖默认值。

---

## 六、测试用例覆盖范围

| 测试脚本 | 覆盖内容 | 类型 |
|----------|---------|------|
| `tests/test_step1_utils.py` | Utils 工具层（安全/文件/响应/错误码） | 单元测试 |
| `tests/test_step2_db.py` | 数据库层（ORM/CRUD） | 单元测试 |
| `tests/test_step3_rag.py` | RAG 引擎（解析/分块/召回/重排/幻觉/问答） | 单元测试 |
| `tests/test_step4_agent.py` | Agent 层（状态图/工具/记忆/反思重试/审计） | 单元测试 |
| `tests/test_step5_services.py` | 业务层（鉴权/权限隔离/上传/问答/Agent/审计） | 单元测试 |
| `tests/test_step6_api.py` | API 层（鉴权/权限/异常格式） | 接口测试 |

**Fake/Mock 注入**：测试注入 `FakeLLM` / `FakeRagPipeline` / `FakeAgentManager` / `HashingEmbedder`，离线运行，不依赖真实大模型与向量库（详见 `docs/experiment_notes.md`）。

---

## 七、业务源码 vs 测试脚本（文件分类）

**业务源码（步骤1-8，禁止修改）**：
```
config/  utils/  db/  ai/rag_engine/  ai/agent_langgraph/
services/  api/  frontend/（app 与 pages，styles 等）
```

**测试脚本（步骤2-6 配套）**：
```
tests/test_step1_utils.py
tests/test_step2_db.py
tests/test_step3_rag.py
tests/test_step4_agent.py
tests/test_step5_services.py
tests/test_step6_api.py
```

**部署工程文件（步骤8）**：
```
requirements.txt  .env.example  .gitignore  Dockerfile
frontend/Dockerfile  docker-compose.yml
```

**文档（步骤8-9）**：
```
README.md  docs/{architecture,module_intro,experiment_guide,deploy,project_overview,checklist,experiment_notes}.md
```
