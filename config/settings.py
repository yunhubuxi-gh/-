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

from pydantic import Field, field_validator, model_validator
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
    # HuggingFace 模型离线加载开关：模型已本地缓存时置 true，避免每次联网校验
    # （国内网络 huggingface.co 常因 SSL 证书/网络原因连不上导致加载失败）
    hf_hub_offline: bool = Field(
        default=True, description="HuggingFace 模型离线加载（true=不联网，用本地缓存）"
    )

    # ========== 多模态图片嵌入配置（可选开关）==========
    enable_image_embed: bool = Field(
        default=False, description="图片向量化总开关；关闭则完全退回原文本 RAG 行为"
    )
    # 图片向量化后端：local=本地 Chinese-CLIP（modelscope），doubao=豆包云端多模态向量化
    image_embed_provider: Literal["local", "doubao"] = Field(
        default="local", description="图片向量化后端 local/doubao"
    )

    # ---- 本地 Chinese-CLIP（provider=local 时生效）----
    # 模型名：默认用 modelscope 开源的 chinese-clip-vit-large-patch14-336px
    # （modelscope 模型 id：damo/multi-modal_clip-vit-large-patch14_336_zh）。
    # 可通过 .env 的 CLIP_MODEL_NAME 更换为任意 modelscope id 或本地目录路径。
    clip_model_name: str = Field(
        default="damo/multi-modal_clip-vit-large-patch14_336_zh",
        description="Chinese-CLIP 模型名（modelscope 模型 id 或本地目录），进程内本地推理",
    )
    clip_device: str = Field(
        default="auto",
        description="Chinese-CLIP 运行设备 auto/cuda/cpu；auto 优先 cuda，无 GPU 自动降级 cpu",
    )
    clip_max_image_side: int = Field(
        default=336,
        description="图片预处理最大边长（等比例缩放），超过则压缩，防止 CLIP 推理 OOM",
    )
    clip_min_image_side: int = Field(
        default=32,
        description="图片预处理最小边长，低于此值的极小无效图片直接过滤，不做向量化",
    )
    clip_download_retry: int = Field(
        default=3, description="Chinese-CLIP 模型下载重试次数，全部失败则关闭图片向量化功能",
    )

    # ---- 豆包云端多模态向量化（provider=doubao 时生效，进程外 API 调用）----
    doubao_api_key: str = Field(default="", description="火山方舟 API Key（ARK_API_KEY）")
    doubao_base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/v3",
        description="火山方舟 Ark API 地址。标准方舟用 /api/v3；Agent Plan 个人版用 /api/plan/v3",
    )
    doubao_embedding_model: str = Field(
        default="doubao-embedding-vision-251215",
        description="豆包多模态向量化模型（文本+图片同空间）。dimensions 参数需 250615 及以上版本",
    )
    doubao_image_embed_dim: int = Field(
        default=1024, description="豆包图片向量维度（1024 或 2048，越小越省存储/费用）"
    )
    doubao_timeout: float = Field(default=60.0, description="豆包向量化调用超时（秒）")
    doubao_max_retry: int = Field(default=3, description="豆包调用重试次数（限流/超时退避）")
    doubao_image_max_side: int = Field(
        default=512,
        description="豆包模式下图片压缩最大边长（压缩越小 token 越少越省钱，建议 448~640）",
    )

    # ---- 兼容旧配置（保留，缺省回退到上面的 clip_* 新配置）----
    multimodal_embedding_model: str = Field(
        default="",
        description="（兼容）旧多模态模型名，CLIP_MODEL_NAME 未配置时回退到此项",
    )
    multimodal_embedding_device: str = Field(default="", description="（兼容）旧设备配置")
    multimodal_embedding_timeout: float = Field(
        default=60.0, description="多模态嵌入调用超时（秒，云端接口用）"
    )
    image_max_side: int = Field(
        default=0, description="（兼容）旧图片最大边长，CLIP_MAX_IMAGE_SIDE 未配置时回退到此项"
    )
    image_vector_top_k: int = Field(default=5, description="图片向量召回条数")

    @field_validator(
        "multimodal_embedding_timeout", "image_max_side", "doubao_timeout",
        "doubao_image_embed_dim", "doubao_max_retry", "doubao_image_max_side",
        mode="before",
    )
    @classmethod
    def _empty_numeric_to_default(cls, v, info):
        """兼容旧 .env 中留空的数值项，空字符串回退默认值，避免启动报错"""
        if isinstance(v, str) and not v.strip():
            return cls.model_fields[info.field_name].default
        return v

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
    min_chunk_size: int = Field(
        default=50,
        description="语义分块后过短的块（字符数低于此值）合并到相邻块，避免语义被切碎",
    )
    vector_top_k: int = Field(default=20)
    hallucination_check_enabled: bool = Field(default=True)

    # ========== RAG 召回优化（新增，全部可通过 .env 覆盖）==========
    # 重排候选数：融合后送入 rerank 的候选条数，应显著大于 reranker_top_n，
    # 否则靠后的相关 chunk 会因进不了重排而被丢弃，导致「文档存在却检索不到」。
    rerank_candidate_k: int = Field(default=20, description="送入重排的候选条数")
    # 检索结果缓存（TTL 内存缓存，重复提问直接命中，跳过检索/改写）
    rag_cache_enabled: bool = Field(default=True, description="检索结果缓存开关")
    rag_cache_ttl: int = Field(default=300, description="缓存过期时间（秒）")
    rag_cache_max_size: int = Field(default=512, description="缓存最大条目数")
    # RAG 调试日志（打印 query 改写、向量/BM25 召回、rerank 结果）
    rag_debug_log: bool = Field(default=False, description="RAG 调试日志开关")
    # query 改写（生成衍生查询提升召回）
    query_rewrite_enabled: bool = Field(default=True, description="query 改写开关")
    query_rewrite_count: int = Field(default=2, description="衍生查询个数（1~2）")
    query_rewrite_timeout: float = Field(default=10.0, description="query 改写 LLM 超时（秒）")
    query_rewrite_max_tokens: int = Field(
        default=1024,
        description="query 改写 LLM 最大输出 token。DeepSeek 为推理模型，过小会导致 "
                    "reasoning 吃光 token 而 content 为空，故默认取较大值",
    )
    # 向量写入批大小（embedding 分片 + 向量库单批写入条数）
    vector_batch_size: int = Field(default=256, description="向量批量写入条数")

    # ========== Agent 配置 ==========
    agent_max_retry: int = Field(default=3, description="Agent 反思重试最大次数")
    agent_short_term_memory_window: int = Field(default=10)
    agent_long_term_memory_enabled: bool = Field(default=True)

    # ========== 试卷命题/校验（双 Agent）配置 ==========
    exam_max_iterate: int = Field(
        default=3,
        description="双 Agent（命题→校验→重生成）最大迭代次数，防止死循环",
    )
    exam_llm_timeout: float = Field(
        default=120.0, description="出题/校验 LLM 调用超时（秒）"
    )
    exam_llm_max_tokens: int = Field(
        default=4096,
        description="出题/校验 LLM 最大输出 token。DeepSeek 为推理模型，过小会导致 "
                    "reasoning 吃光 token 而 content 为空，故默认取较大值",
    )
    exam_rag_top_k: int = Field(
        default=6, description="出题/校验时 RAG 召回课件原文条数"
    )
    exam_temperature: float = Field(
        default=0.0, description="出题/校验 LLM 温度（0=稳定，降低随机性）"
    )
    exam_default_difficulty: str = Field(
        default="medium", description="试卷默认难度 easy/medium/hard"
    )

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

# 立即应用 HuggingFace 离线模式，必须在此处（模块加载时）设置，早于任何
# huggingface_hub / transformers / sentence_transformers 的导入。
# 这些库在「导入时」就把 HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE 读成常量，
# 若等到客户端 __init__ 里再设 env 就太迟了（此前已因此导致本地模型加载时仍联网报 SSL 错）。
if settings.hf_hub_offline:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
