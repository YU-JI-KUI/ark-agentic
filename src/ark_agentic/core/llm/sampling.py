"""LLM 生成参数配置（OpenAI 顶层 + vLLM/SGLang extra_body 扩展）。

默认值对齐 Qwen3-Next-Instruct 金融业务场景：低温度、工具调用遵循、输出稳定。
其他模型（Llama/DeepSeek/GLM）可通过 classmethod overrides 或 model_copy 覆盖。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SamplingConfig(BaseModel):
    """LLM 生成参数（统一入口）。

    分层输出：
    - to_chat_openai_kwargs() → OpenAI v1 顶层可接受的参数
    - to_extra_body()         → vLLM/SGLang 扩展参数（走 extra_body）

    场景预设（均支持 **overrides 自定义）：
    - for_chat          对话，低温度 + 工具调用遵循（默认）
    - for_extraction    结构化 JSON 抽取，贪婪 + 可复现
    - for_summarization 摘要 / 蒸馏，稳定但保留流畅度
    """

    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    top_k: int = Field(default=20, ge=0)
    repetition_penalty: float = Field(default=1.05, ge=0.0)
    presence_penalty: float = Field(default=0.6, ge=-2.0, le=2.0)
    min_p: float = Field(default=0.0, ge=0.0, le=1.0)
    max_tokens: int = Field(default=4096, gt=0)
    seed: int | None = None
    enable_thinking: bool = False

    @classmethod
    def for_chat(cls, **overrides: Any) -> "SamplingConfig":
        """金融业务对话 —— 稳定 + 工具调用遵循优先（默认值即此预设）。"""
        return cls(**overrides)

    @classmethod
    def for_extraction(cls, **overrides: Any) -> "SamplingConfig":
        """结构化抽取（memory flush / intent parse）—— 确定性 + 可复现。"""
        base: dict[str, Any] = dict(
            temperature=0.0,
            top_p=1.0,
            top_k=1,
            repetition_penalty=1.0,
            presence_penalty=0.0,
            min_p=0.0,
            seed=42,
            max_tokens=2048,
        )
        return cls(**{**base, **overrides})

    @classmethod
    def for_summarization(cls, **overrides: Any) -> "SamplingConfig":
        """摘要 / 蒸馏（dream / compaction）—— 稳定但保留流畅度。"""
        base: dict[str, Any] = dict(
            temperature=0.2,
            top_p=0.8,
            top_k=20,
            repetition_penalty=1.1,
            presence_penalty=0.0,
            min_p=0.0,
            max_tokens=1024,
        )
        return cls(**{**base, **overrides})

    def to_chat_openai_kwargs(self) -> dict[str, Any]:
        """OpenAI v1 顶层参数（ChatOpenAI 构造时直接透传）。"""
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "presence_penalty": self.presence_penalty,
            "max_tokens": self.max_tokens,
        }

    def to_extra_body(self) -> dict[str, Any]:
        """vLLM/SGLang 扩展参数（走 ChatOpenAI.extra_body）。

        seed=None 时不写入 body（vLLM 自行随机，避免"重试失效"）。
        """
        body: dict[str, Any] = {
            "top_k": self.top_k,
            "repetition_penalty": self.repetition_penalty,
            "min_p": self.min_p,
            "chat_template_kwargs": {
                "enable_thinking": self.enable_thinking,
                "thinking": self.enable_thinking,
            },
        }
        if self.seed is not None:
            body["seed"] = self.seed
        return body
