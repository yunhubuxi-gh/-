# 部署测试说明文档

本文档说明如何使用 Docker Compose 一键拉起整套系统，并验证各服务之间的连通性。

---

## 一、Docker Compose 一键部署

### 前置条件

- 已安装 Docker（20.10+）与 Docker Compose（v2+）
- 已准备一个大模型 API Key（DeepSeek / OpenAI / Qwen 任意一种）

### 部署步骤

```bash
# 1. 进入项目根目录
cd enterprise-kb-assistant

# 2. 生成并编辑环境变量
cp .env.example .env
# 编辑 .env，至少填写：
#   LLM_API_KEY=sk-你的密钥
#   其余项可用默认值（数据库走容器内 PostgreSQL，向量库走容器内 Chroma）

# 3. 一键构建并启动全部服务
docker-compose up -d --build

# 4. 查看服务状态（三个服务应均为 running/healthy）
docker-compose ps
```

### 启动依赖顺序

`docker-compose.yml` 已配置依赖顺序，确保服务按正确顺序启动：

1. **postgres** 优先启动，并通过 `healthcheck`（`pg_isready`）确认就绪
2. **backend** 在 postgres `healthy` 后启动；启动时自动执行 `python -m db.init_db` 完成建表与管理员初始化
3. **frontend** 在 backend 启动后启动

### 端口映射

| 服务 | 容器端口 | 宿主机端口 | 说明 |
|------|---------|-----------|------|
| frontend | 8501 | 8501 | Streamlit 前端 |
| backend | 8000 | 8000 | FastAPI 后端 |
| postgres | 5432 | 5432 | PostgreSQL（生产可移除对外暴露） |

### 数据持久化卷

| 卷名 | 挂载路径 | 内容 |
|------|---------|------|
| `pg_data` | `/var/lib/postgresql/data` | PostgreSQL 数据 |
| `upload_data` | `/app/data/uploads` | 上传文档（文件系统） |
| `vector_data` | `/app/data/vector_store` | Chroma 向量库 |
| `log_data` | `/app/data/logs` | 应用/审计日志 |
| `bm25_data` | `/app/data/bm25_index` | BM25 索引 |
| `memory_data` | `/app/data/long_term_memory` | Agent 长期记忆 |

> 容器删除后卷数据不丢失；`docker-compose down -v` 会**同时删除卷**，请谨慎使用。

---

## 二、连通性验证

### 1. 验证后端健康

```bash
# 后端应返回 OpenAPI 规范 JSON（HTTP 200）
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/openapi.json
# 期望输出：200
```

### 2. 验证后端注册 / 登录接口

```bash
# 注册一个测试账号
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"Test@123"}'
# 期望：{"code":0,"message":"注册成功",...}

# 登录获取 token
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"Test@123"}'
# 期望返回 data.access_token
```

### 3. 验证前端连通后端

浏览器访问 `http://localhost:8501`：

1. 出现登录页（居中卡片样式）→ 前端容器正常
2. 使用 `admin / Teacher@123` 或刚注册的账号登录成功 → 前端已通过 `FRONTEND_API_BASE_URL=http://backend:8000` 连通后端
3. 创建知识库、上传一个 MD 文档、发起一次问答 → 全链路（前端 → 后端 → RAG 引擎 → 向量库）正常

### 4. 容器内直连验证

```bash
# 进入 backend 容器，确认数据库表已创建、管理员已初始化
docker-compose exec backend python -c "from db.crud import user_crud; from db.session import SyncSessionLocal; db=SyncSessionLocal(); print('admin 存在:', user_crud.get_by_username(db,'admin') is not None); db.close()"
# 期望输出：admin 存在: True

# 确认 postgres 数据持久化
docker-compose exec postgres psql -U kbuser -d kb_assistant -c "SELECT count(*) FROM users;"
# 期望：能查询到 users 表（count >= 1）
```

---

## 三、切换向量库（Chroma → Milvus）

默认使用容器内 Chroma。切换到外部 Milvus：

```bash
# 1. 准备外部 Milvus 服务（如 docker run milvusdb/milvus:... 或云服务）
# 2. 修改 .env：
#    VECTOR_STORE_TYPE=milvus
#    MILVUS_HOST=<你的Milvus主机>
#    MILVUS_PORT=19530
# 3. 重启后端
docker-compose up -d --build backend
```

> 需同时取消 `requirements.txt` 中 `pymilvus==2.4.4` 的注释并重新构建镜像。

---

## 四、常见问题排查

| 现象 | 排查 |
|------|------|
| 后端启动失败，日志报 `Connection refused` 连接 postgres | 确认 postgres 容器 `healthy`；`DATABASE_URL` 中 host 应为 `postgres`（服务名） |
| 前端登录报「无法连接后端服务」 | 确认 `.env` 的 `FRONTEND_API_BASE_URL=http://backend:8000`，且 backend 已启动 |
| 问答返回「大模型调用失败」 | 检查 `.env` 的 `LLM_API_KEY` / `LLM_BASE_URL` 是否正确 |
| 上传文档后向量化失败 | 查看 `docker-compose logs backend`；确认嵌入模型可下载（首次需联网下载 BGE 模型） |
| 文档向量化卡住 | 首次加载 sentence-transformers 模型较慢，稍等片刻 |

### 查看日志

```bash
docker-compose logs -f backend      # 后端日志
docker-compose logs -f frontend     # 前端日志
docker-compose logs -f postgres     # 数据库日志
```

### 停止 / 清理

```bash
docker-compose down                 # 停止（保留数据卷）
docker-compose down -v              # 停止并删除数据卷（危险，会清空数据）
```
