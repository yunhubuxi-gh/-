# ============================================================
# 后端镜像（FastAPI）
# 构建：docker build -t kb-assistant-backend .
# ============================================================
FROM python:3.10-slim

# 系统依赖：psycopg2-binary 需要 libpq（已含在二进制包内），
# 其他重型依赖（torch/paddle/CLIP）默认不装，保持镜像精简。
#
# 图片多模态向量化（Chinese-CLIP）为【可选】功能：
#   不需要图片功能时可保持 requirements.txt 中 torch/transformers/modelscope/pillow 注释，
#   并保持 .env 的 ENABLE_IMAGE_EMBED=false，镜像不含 CLIP 相关依赖，体积更小。
#   需要图片功能时：取消 requirements.txt 中对应行注释（或下方单独安装），并设 ENABLE_IMAGE_EMBED=true。
#
#   # 需要图片功能时，取消下面注释单独安装 CLIP 依赖（进程内本地推理，不引入 Ollama）：
#   RUN pip install --no-cache-dir torch transformers modelscope pillow
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
