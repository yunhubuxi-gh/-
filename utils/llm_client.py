"""
LLM 大模型客户端封装
统一封装 OpenAI 兼容接口，支持切换：OpenAI / DeepSeek / Qwen / Ollama
所有 AI 能力层模块统一通过此客户端调用大模型，杜绝各模块重复写调用逻辑。
"""
from __future__ import annotations

from typing import List, Dict, Optional, AsyncIterator
from openai import OpenAI, AsyncOpenAI

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class LLMClient:
    """
    大模型客户端封装类。
    - 统一 chat completions 接口
    - 兼容 OpenAI SDK 协议，可无缝切换底层模型提供商
    - 支持同步/异步调用
    - 支持流式输出
    - 内置失败重试与日志记录
    """

    def __init__(self) -> None:
        self.provider = settings.llm_provider
        self.base_url = settings.llm_base_url
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self.temperature = settings.llm_temperature
        self.max_tokens = settings.llm_max_tokens
        self.timeout = settings.llm_timeout

        # 同步客户端（OpenAI SDK 自动携带 Authorization: Bearer <api_key> 鉴权头）
        self._client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
        )
        # 异步客户端
        self._async_client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
        )

        logger.info(
            f"LLMClient 初始化完成: provider={self.provider}, "
            f"model={self.model}, base_url={self.base_url}"
        )

    # ==================== 同步调用 ====================
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        thinking_disabled: bool = False,
        **kwargs,
    ) -> str:
        """
        同步对话补全

        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}]
            temperature: 采样温度，默认取配置
            max_tokens: 最大输出 token 数
            model: 覆盖默认模型
            thinking_disabled: True 时关闭 DeepSeek 推理模型的思考模式
                （thinking={"type":"disabled"}），避免 reasoning 吃光 max_tokens
                导致 content 为空——出题/校验等需要稳定结构化 JSON 输出的场景必须置 True。
            **kwargs: 其他传递给 OpenAI API 的参数

        Returns:
            模型生成的文本内容
        """
        try:
            # 思考模式控制：DeepSeek v4 推理模型默认开启思考，reasoning 会先于 content 输出，
            # 若 reasoning 吃满 max_tokens 则 content 为空。结构化输出场景关闭思考。
            extra_body = kwargs.pop("extra_body", None) or {}
            if thinking_disabled:
                extra_body["thinking"] = {"type": "disabled"}
            create_kwargs = dict(
                model=model or self.model,
                messages=messages,
                temperature=temperature if temperature is not None else self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                **kwargs,
            )
            if extra_body:
                create_kwargs["extra_body"] = extra_body
            response = self._client.chat.completions.create(**create_kwargs)
            content = response.choices[0].message.content or ""
            logger.debug(
                f"LLM 调用成功: model={self.model}, "
                f"prompt_tokens={response.usage.prompt_tokens if response.usage else 'N/A'}, "
                f"completion_tokens={response.usage.completion_tokens if response.usage else 'N/A'}"
            )
            return content
        except Exception as e:
            logger.error(f"LLM 调用失败: {str(e)}")
            raise RuntimeError(f"大模型调用失败: {str(e)}") from e

    # ==================== 流式调用 ====================
    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        **kwargs,
    ):
        """
        流式对话补全，返回生成器

        Yields:
            每次返回的文本片段字符串
        """
        try:
            stream = self._client.chat.completions.create(
                model=model or self.model,
                messages=messages,
                temperature=temperature if temperature is not None else self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                stream=True,
                **kwargs,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"LLM 流式调用失败: {str(e)}")
            raise RuntimeError(f"大模型流式调用失败: {str(e)}") from e

    # ==================== 异步调用 ====================
    async def achat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> str:
        """异步对话补全"""
        try:
            response = await self._async_client.chat.completions.create(
                model=model or self.model,
                messages=messages,
                temperature=temperature if temperature is not None else self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                **kwargs,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"LLM 异步调用失败: {str(e)}")
            raise RuntimeError(f"大模型异步调用失败: {str(e)}") from e

    # ==================== 异步流式 ====================
    async def achat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        """异步流式对话补全"""
        try:
            stream = await self._async_client.chat.completions.create(
                model=model or self.model,
                messages=messages,
                temperature=temperature if temperature is not None else self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"LLM 异步流式调用失败: {str(e)}")
            raise RuntimeError(f"大模型异步流式调用失败: {str(e)}") from e


# 全局单例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
