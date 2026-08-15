# ============================================================
# 后端镜像（FastAPI）
# 构建：docker build -t kb-assistant-backend .
# ============================================================
FROM python:3.10-slim

# 系统依赖：psycopg2-binary 需要 libpq（已含在二进制包内），
# 其他重型依赖（torch/paddle）默认不装，保持镜像精简
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先复制依赖清单安装，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目源码
COPY . .

# 数据目录（挂载卷：uploads / vector_store / logs / bm25_index / long_term_memory）
RUN mkdir -p /app/data/uploads /app/data/vector_store /app/data/logs \
    /app/data/bm25_index /app/data/long_term_memory /app/data/exports

EXPOSE 8000

# 启动：数据库初始化（复用 db/init_db.py，建表 + 初始化管理员）+ 后端服务
CMD ["sh", "-c", "python -m db.init_db && uvicorn api.main:app --host 0.0.0.0 --port 8000"]
