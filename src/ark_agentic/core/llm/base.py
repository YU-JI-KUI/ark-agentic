"""
LLM Client 基础定义

定义 LLM 客户端协议和基础类型。
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Literal, Protocol


# ============ Dynamic Values ============


class DynamicValues:
    """常用动态值生成器

    用于 extra_headers 和 extra_body 中需要动态生成的值。

    示例:
        extra_headers={
            "trace-appId": "my-app",                    # 静态值
            "trace-requestId": DynamicValues.uuid(),   # 每次请求生成新 UUID
            "trace-userId": DynamicValues.from_kwargs("user_id"),
        }
    """

    @staticmethod
    def uuid() -> Callable[[dict[str, Any]], str]:
        """每次请求生成新 UUID"""
        return lambda ctx: str(uuid.uuid4())

    @staticmethod
    def timestamp() -> Callable[[dict[str, Any]], int]:
        """生成时间戳（秒）"""
        return lambda ctx: int(time.time())

    @staticmethod
    def timestamp_ms() -> Callable[[dict[str, Any]], int]:
        """生成时间戳（毫秒）"""
        return lambda ctx: int(time.time() * 1000)

    @staticmethod
    def from_kwargs(key: str, default: Any = "") -> Callable[[dict[str, Any]], Any]:
        """从 chat() 的 kwargs 获取值"""
        return lambda ctx: ctx.get(key, default)


# ============ LLM Client Protocol ============


class LLMClientProtocol(Protocol):
    """LLM 客户端协议

    定义 LLM 调用接口，支持不同的 LLM 提供商。
    """

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        """发送聊天请求

        Args:
            messages: 消息列表（OpenAI 格式）
            tools: 工具定义列表
            stream: 是否流式输出
            **kwargs: 其他参数（temperature, max_tokens 等）

        Returns:
            非流式：完整响应
            流式：事件迭代器
        """
        ...


# ============ Configuration ============


@dataclass
class LLMConfig:
    """LLM 配置"""

    # 提供商
    provider: Literal["deepseek", "openai", "internal", "simple"] = "deepseek"

    # API 配置
    api_key: str = ""
    base_url: str = ""

    # 模型
    model: str = "deepseek-chat"

    # 内部 API 专用
    authorization: str = ""
    trace_appid: str = ""

    # Unified Internal API 专用
    trace_source: str = ""
    trace_user_id: str = ""

    # 默认参数
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 60.0

    # 重试配置
    max_retries: int = 3
    retry_delay: float = 1.0

    # 扩展参数（用于 OpenAI 兼容 API 添加自定义 headers/body）
    # 值可以是静态值或 Callable[[dict], Any] 动态值
    extra_headers: dict[str, Any] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)


# ============ Response Types ============


@dataclass
class LLMUsage:
    """Token 使用统计"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMUsage:
        return cls(
            prompt_tokens=data.get("prompt_tokens", 0) or data.get("input_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0) or data.get("output_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
        )


@dataclass
class LLMToolCall:
    """工具调用"""

    id: str
    name: str
    arguments: str  # JSON 字符串


@dataclass
class LLMMessage:
    """LLM 消息"""

    role: str
    content: str | None = None
    tool_calls: list[LLMToolCall] | None = None


@dataclass
class LLMChoice:
    """响应选项"""

    index: int = 0
    message: LLMMessage | None = None
    finish_reason: str | None = None


@dataclass
class LLMResponse:
    """统一 LLM 响应格式"""

    id: str = ""
    model: str = ""
    choices: list[LLMChoice] = field(default_factory=list)
    usage: LLMUsage | None = None
    created: int = 0

    @classmethod
    def from_openai_dict(cls, data: dict[str, Any]) -> LLMResponse:
        """从 OpenAI 格式响应构建"""
        choices = []
        for choice_data in data.get("choices", []):
            message_data = choice_data.get("message", {})
            tool_calls = None

            if message_data.get("tool_calls"):
                tool_calls = [
                    LLMToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("function", {}).get("name", ""),
                        arguments=tc.get("function", {}).get("arguments", "{}"),
                    )
                    for tc in message_data["tool_calls"]
                ]

            message = LLMMessage(
                role=message_data.get("role", "assistant"),
                content=message_data.get("content"),
                tool_calls=tool_calls,
            )

            choices.append(
                LLMChoice(
                    index=choice_data.get("index", 0),
                    message=message,
                    finish_reason=choice_data.get("finish_reason"),
                )
            )

        usage = None
        if data.get("usage"):
            usage = LLMUsage.from_dict(data["usage"])

        return cls(
            id=data.get("id", ""),
            model=data.get("model", ""),
            choices=choices,
            usage=usage,
            created=data.get("created", 0),
        )

    def to_openai_dict(self) -> dict[str, Any]:
        """转换为 OpenAI 格式（用于兼容现有代码）"""
        choices = []
        for choice in self.choices:
            choice_dict: dict[str, Any] = {
                "index": choice.index,
                "finish_reason": choice.finish_reason,
            }

            if choice.message:
                message_dict: dict[str, Any] = {
                    "role": choice.message.role,
                    "content": choice.message.content,
                }

                if choice.message.tool_calls:
                    message_dict["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments,
                            },
                        }
                        for tc in choice.message.tool_calls
                    ]

                choice_dict["message"] = message_dict

            choices.append(choice_dict)

        result: dict[str, Any] = {
            "id": self.id,
            "model": self.model,
            "choices": choices,
            "created": self.created,
        }

        if self.usage:
            result["usage"] = {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "total_tokens": self.usage.total_tokens,
            }

        return result


# ============ Base Client ============


class BaseLLMClient(ABC):
    """LLM 客户端基类"""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        """发送聊天请求"""
        ...

    async def close(self) -> None:
        """关闭客户端（清理资源）"""
        pass
