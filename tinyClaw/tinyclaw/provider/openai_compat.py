"""
OpenAI 兼容 LLM Provider
========================
封装 OpenAI SDK，提供统一的 chat / stream_chat 接口。
支持自动重试、流式输出、工具调用。
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Generator, Optional

from openai import OpenAI

from tinyclaw.config import ProviderConfig


@dataclass
class ChatResponse:
    """聊天响应结构。"""
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict = field(default_factory=dict)
    raw: Any = None


@dataclass
class StreamChunk:
    """流式输出片段。"""
    delta_content: str = ""
    tool_calls_delta: list[dict] = field(default_factory=list)
    finish_reason: str = ""
    is_final: bool = False


class OpenAICompatProvider:
    """
    OpenAI 兼容 Provider。

    支持所有 OpenAI 兼容 API（OpenAI / Azure / 本地部署等）。
    提供同步 chat 和流式 stream_chat 两种调用方式。
    """

    def __init__(self, config: ProviderConfig):
        """
        初始化 Provider。

        参数:
            config: Provider 配置
        """
        self.config = config
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
        )
        self.default_model = config.model

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ChatResponse:
        """
        同步聊天接口，带自动重试。

        参数:
            messages: 消息列表
            tools: 工具定义列表
            model: 模型名称（留空用默认）
            max_tokens: 最大 token 数
            temperature: 温度参数

        返回:
            ChatResponse 对象
        """
        model = model or self.default_model
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature

        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.client.chat.completions.create(**kwargs)
                msg = response.choices[0].message

                # 解析 tool_calls
                tool_calls = []
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        })

                return ChatResponse(
                    content=msg.content or "",
                    tool_calls=tool_calls,
                    finish_reason=response.choices[0].finish_reason or "",
                    usage={
                        "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                        "total_tokens": getattr(response.usage, "total_tokens", 0),
                    } if response.usage else {},
                    raw=response,
                )
            except Exception as e:
                last_error = e
                if attempt < self.config.max_retries:
                    wait = 2 ** attempt
                    print(f"  [Provider] 第 {attempt + 1} 次重试，等待 {wait}s: {e}")
                    time.sleep(wait)

        raise last_error or RuntimeError("未知 Provider 错误")

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Generator[StreamChunk, None, None]:
        """
        流式聊天接口。

        参数:
            messages: 消息列表
            tools: 工具定义列表
            model: 模型名称
            max_tokens: 最大 token 数
            temperature: 温度参数

        返回:
            StreamChunk 生成器
        """
        model = model or self.default_model
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature

        response = self.client.chat.completions.create(**kwargs)

        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            # 解析 tool_calls delta
            tc_delta = []
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    tc_delta.append({
                        "index": tc.index,
                        "id": getattr(tc, "id", None),
                        "type": getattr(tc, "type", None),
                        "function": {
                            "name": getattr(tc.function, "name", None) if tc.function else None,
                            "arguments": getattr(tc.function, "arguments", "") if tc.function else "",
                        },
                    })

            yield StreamChunk(
                delta_content=delta.content or "",
                tool_calls_delta=tc_delta,
                finish_reason=finish_reason or "",
                is_final=finish_reason is not None,
            )

    def simple_complete(self, prompt: str, system: str = "", max_tokens: int = 300) -> str:
        """
        简易补全接口，用于内部任务（如摘要）。

        参数:
            prompt: 用户 prompt
            system: 系统 prompt
            max_tokens: 最大 token 数

        返回:
            补全文本
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self.chat(messages, max_tokens=max_tokens)
        return resp.content
