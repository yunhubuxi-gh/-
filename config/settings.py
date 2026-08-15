"""
全局配置模块
基于 pydantic-settings 从 .env / 环境变量加载配置，单例模式。
支持向量库二选一、异步任务引擎切换、大模型提供商切换。
"""
import os
from pathlib import Path
from typing import Literal
from functools import lru_cache

import logging

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 占位符片段：用于识别「未填写真实密钥」的默认值，避免把占位符当真 key 使用
_PLACEHOLDER_HINTS = ("sk-your", "sk-xxxx", "change-me", "your-", "placeholder", "ollama")


def _is_blank_or_placeholder(value) -> bool:
    """判断配置值是否为空或仍为占位符（未填真实密钥）"""
    if value is None:
        return True
    s = str(value).strip().lower()
    if not s:
        return True
    return s.startswith(_PLACEHOLDER_HINTS)


# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """
    全局配置类，所有配置项集中在此处。
    通过 .env 文件或环境变量覆盖。
    """

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ========== 应用基础配置 ==========
    app_name: str = Field(default="企业私有知识库智能助手平台")
    app_version: str = Field(default="1.0.0")
    debug: bool = Field(default=False)
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    # ========== 数据库配置 ==========
    database_url: str = Field(
        default="sqlite:///./data/app.db",
        description="PostgreSQL/SQLite 连接串，生产环境建议 PostgreSQL",
    )

    # ========== JWT 鉴权配置 ==========
    jwt_secret_key: str = Field(default="change-me-in-production-please")
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=120)
    jwt_refresh_token_expire_days: int = Field(default=7)

    # ========== DeepSeek 统一配置（OpenAI 兼容协议）==========
    deepseek_api_key: str = Field(default="", description="DeepSeek API Key（.env 必填，禁止硬编码）")
    deepseek_base_url: str = Field(default="https://api.deepseek.com", description="DeepSeek Base URL")

    # ========== 大模型配置（OpenAI 兼容接口，默认走 DeepSeek）==========
    llm_provider: Literal["openai", "deepseek", "qwen", "ollama"] = Field(default="deepseek")
    llm_base_url: str = Field(default="https://api.deepseek.com")
    llm_api_key: str = Field(default="", description="留空则回退 DEEPSEEK_API_KEY")
    llm_model: str = Field(default="deepseek-v4-flash")
    llm_temperature: float = Field(default=0.2)
    llm_max_tokens: int = Field(default=2048)
    llm_timeout: float = Field(default=60.0, description="LLM 请求超时（秒）")

    # ========== 嵌入模型配置 ==========
    embedding_provider: Literal["openai", "bge", "huggingface"] = Field(default="bge")
    embedding_base_url: str = Field(default="")
    embedding_api_key: str = Field(default="")
    embedding_model: str = Field(default="BAAI/bge-small-zh-v1.5")
    embedding_dimension: int = Field(default=512)
    embedding_batch_size: int = Field(default=32)

    # ========== 多模态图片嵌入配置（本地 Chinese-CLIP，可选开关）==========
    enable_image_embed: bool = Field(
        default=False, description="图片向量化总开关；关闭则完全退回原文本 RAG 行为"
    )
    multimodal_embedding_model: str = Field(
        default="OFA-Sys/chinese-clip-vit-base-patch16",
        description="多模态（图文）嵌入模型名，本地加载，与文本 BGE 分离",
    )
    multimodal_embedding_device: str = Field(default="cpu", description="多模态模型设备 cpu/cuda")
    multimodal_embedding_timeout: float = Field(
        default=60.0, description="多模态嵌入调用超时（秒，云端接口用）"
    )
    image_max_side: int = Field(
        default=1024, description="图片预处理压缩的最大边长（避免大图导致接口/显存报错）"
    )
    image_vector_top_k: int = Field(default=5, description="图片向量召回条数")

    # ========== 向量数据库配置（二选一，通过 VECTOR_STORE_TYPE 切换）==========
    vector_store_type: Literal["chroma", "milvus"] = Field(
        default="chroma",
        description="向量库类型，chroma 用于本地开发，milvus 用于生产部署",
    )
    # Chroma 配置
    chroma_persist_dir: str = Field(default="./data/vector_store")
    # Milvus 配置
    milvus_host: str = Field(default="localhost")
    milvus_port: int = Field(default=19530)
    milvus_alias: str = Field(default="default")

    # ========== BM25 召回配置 ==========
    bm25_index_dir: str = Field(default="./data/bm25_index")
    bm25_top_k: int = Field(default=20)

    # ========== 重排模型配置 ==========
    reranker_model: str = Field(default="BAAI/bge-reranker-base")
    reranker_top_n: int = Field(default=5)
    reranker_device: str = Field(default="cpu")

    # ========== RAG 通用配置 ==========
    chunk_size: int = Field(default=512)
    chunk_overlap: int = Field(default=50)
    semantic_chunk_threshold: float = Field(
        default=0.75,
        description="语义分块相似度阈值，低于此值则切分",
    )
    vector_top_k: int = Field(default=20)
    hallucination_check_enabled: bool = Field(default=True)

    # ========== Agent 配置 ==========
    agent_max_retry: int = Field(default=3, description="Agent 反思重试最大次数")
    agent_short_term_memory_window: int = Field(default=10)
    agent_long_term_memory_enabled: bool = Field(default=True)

    # ========== 异步任务配置 ==========
    async_task_engine: Literal["background", "celery"] = Field(
        default="background",
        description="异步任务引擎，background 用 FastAPI BackgroundTasks（开发），celery 用于生产",
    )
    celery_broker_url: str = Field(default="redis://localhost:6379/0")
    celery_result_backend: str = Field(default="redis://localhost:6379/1")

    # ========== OCR 配置 ==========
    ocr_enabled: bool = Field(default=True)
    ocr_engine: Literal["paddleocr", "tesseract"] = Field(default="paddleocr")
    ocr_lang: str = Field(default="ch")

    # ========== 文件存储配置 ==========
    upload_dir: str = Field(default="./data/uploads")
    export_dir: str = Field(default="./data/exports")
    max_file_size_mb: int = Field(default=100)
    allowed_file_types: list[str] = Field(
        default_factory=lambda: [".pdf", ".docx", ".md", ".txt", ".png", ".jpg", ".jpeg"]
    )

    # ========== 日志配置 ==========
    log_level: str = Field(default="INFO")
    log_dir: str = Field(default="./data/logs")
    audit_log_enabled: bool = Field(default=True)

    # ========== 前端配置 ==========
    frontend_url: str = Field(default="http://localhost:8501")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8501", "http://127.0.0.1:8501"]
    )

    # ========== 配置解析与校验 ==========
    @model_validator(mode="after")
    def _resolve_llm_credentials(self):
        """DeepSeek 统一 key/base_url 回退填充 + 启动时密钥校验"""
        if self.llm_provider == "deepseek":
            if _is_blank_or_placeholder(self.llm_base_url):
                self.llm_base_url = self.deepseek_base_url
            if _is_blank_or_placeholder(self.llm_api_key):
                self.llm_api_key = self.deepseek_api_key

        # 启动校验：密钥为空 / 仍为占位符时给出明确日志警告
        if _is_blank_or_placeholder(self.llm_api_key):
            logger.warning(
                "⚠️  LLM API Key 未配置（DEEPSEEK_API_KEY / LLM_API_KEY 为空或仍为占位符），"
                "大模型调用将失败。请在 .env 中填入真实 Key。"
            )
        else:
            logger.info(
                f"LLM 配置就绪: provider={self.llm_provider}, model={self.llm_model}, "
                f"base_url={self.llm_base_url}, timeout={self.llm_timeout}s"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    获取全局配置单例。
    使用 lru_cache 确保整个应用共用同一份配置实例。
    """
    return Settings()


settings = get_settings()
