# ============================================================
# 前端镜像（Streamlit）
# 构建：docker build -t kb-assistant-frontend -f frontend/Dockerfile .
#
# 说明：前端只通过 HTTP 调用后端，仅需 streamlit + requests + 配置读取
#       （frontend/config.py 依赖 config.settings 的 pydantic-settings），
#       不安装 torch / chromadb 等重型依赖，保持镜像精简。
# ============================================================
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 只安装前端运行所需的最少依赖
RUN pip install --no-cache-dir \
    streamlit==1.61.1 \
    requests==2.32.5 \
    pydantic==2.9.2 \
    pydantic-settings==2.5.2 \
    python-dotenv==1.0.1

# 复制项目源码（前端需要 import 根目录的 config.settings）
COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "frontend/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
