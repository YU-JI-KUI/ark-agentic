"""
LLM Client 工厂（ChatOpenAI 统一入口）

统一 PA 内部模型和 OpenAI 兼容模型的创建，返回 BaseChatModel。

模型分类：
1. DeepSeek 等 OpenAI 兼容模型 — 标准 ChatOpenAI
2. PA 内部模型：
   A. PA-JT-*: JT transport（RSA + HMAC 签名 + body 注入）
   B. PA-SX-*: SX transport（trace headers + body 注入）
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


# ============ 模型枚举 ============


class PAModel(str, Enum):
    """PA 内部模型枚举"""

    PA_JT_80B = "PA-JT-80B"
    PA_SX_80B = "PA-SX-80B"
    PA_SX_235B = "PA-SX-235B"


# ============ 模型配置 ============


@dataclass
class PAModelConfig:
    """PA 单个模型的连接配置"""

    base_url: str
    model_name: str
    model_type: Literal["jt", "sx"]
    # SX 系列
    api_key: str = ""
    trace_app_id: str = ""
    # JT 系列
    open_api_code: str = ""
    open_api_credential: str = ""
    rsa_private_key: str = ""
    gpt_app_key: str = ""
    gpt_app_secret: str = ""
    scene_id: str = ""


def _load_pa_model_config(model: PAModel) -> PAModelConfig:
    """从环境变量加载 PA 模型配置（延迟读取）。

    Raises:
        ValueError: 如果必需的环境变量缺失
    """
    if model == PAModel.PA_JT_80B:
        base_url = os.getenv("PA_JT_BASE_URL", "")
        if not base_url:
            raise ValueError(
                "PA_JT_BASE_URL is required for PA-JT models. "
                "Please set it in your .env file."
            )
        return PAModelConfig(
            base_url=base_url,
            model_name="PA-JT-80B",
            model_type="jt",
            open_api_code=os.getenv("PA_JT_OPEN_API_CODE", ""),
            open_api_credential=os.getenv("PA_JT_OPEN_API_CREDENTIAL", ""),
            rsa_private_key=os.getenv("PA_JT_RSA_PRIVATE_KEY", ""),
            gpt_app_key=os.getenv("PA_JT_GPT_APP_KEY", ""),
            gpt_app_secret=os.getenv("PA_JT_GPT_APP_SECRET", ""),
            scene_id=os.getenv("PA_JT_SCENE_ID", ""),
        )

    # PA-SX 系列
    base_url = os.getenv("PA_SX_BASE_URL", "")
    if not base_url:
        raise ValueError(
            "PA_SX_BASE_URL is required for PA-SX models. "
            "Please set it in your .env file."
        )

    app_id_env = (
        "PA_SX_80B_APP_ID" if model == PAModel.PA_SX_80B else "PA_SX_235B_APP_ID"
    )
    api_key_env = (
        "PA_SX_80B_API_KEY" if model == PAModel.PA_SX_80B else "PA_SX_235B_API_KEY"
    )
    return PAModelConfig(
        base_url=base_url,
        model_name=model.value,
        model_type="sx",
        api_key=os.getenv(api_key_env, ""),
        trace_app_id=os.getenv(app_id_env, ""),
    )


# ============ ChatOpenAI 工厂 ============


def create_chat_model(
    model: str | PAModel = "PA-SX-80B",
    *,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    streaming: bool = False,
    enable_thinking: bool = False,
    # DeepSeek / OpenAI 兼容专用
    api_key: str | None = None,
    base_url: str | None = None,
    # 额外参数（PA 模型：合并进 ChatOpenAI.extra_body）
    extra_body: dict[str, Any] | None = None,
) -> "BaseChatModel":
    """创建 LangChain ChatOpenAI 实例，返回 BaseChatModel。

    Args:
        model: 模型名称。PA-JT-80B / PA-SX-80B / PA-SX-235B / deepseek-chat / 其他
        temperature: 温度
        max_tokens: 最大 token
        streaming: 是否启用流式
        enable_thinking: 是否启用 thinking
        api_key: API Key（DeepSeek 等需要；PA 模型从环境变量读取）
        base_url: API 端点（DeepSeek 等需要；PA 模型从环境变量读取）
        extra_body: 额外 body 字段，合并进 ChatOpenAI.extra_body（PA 模型）

    Returns:
        BaseChatModel 实例（ChatOpenAI 子类）

    Examples:
        # PA-SX（默认）
        llm = create_chat_model("PA-SX-80B")

        # PA-JT（需要网关签名）
        llm = create_chat_model("PA-JT-80B")

        # DeepSeek
        llm = create_chat_model("deepseek-chat", api_key="sk-xxx")
    """
    model_str = model.value if isinstance(model, PAModel) else model

    try:
        from langchain_openai import ChatOpenAI  # noqa: F401 – eagerly validate install
    except ImportError as e:
        raise ImportError(
            f"langchain-openai is required. Install with: pip install langchain-openai. {e}"
        ) from e

    if model_str.startswith("PA-JT"):
        from .pa_jt_llm import create_pa_jt_llm
        config = _load_pa_model_config(PAModel(model_str))
        return create_pa_jt_llm(
            config,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            enable_thinking=enable_thinking,
            extra_body_override=extra_body,
        )

    if model_str.startswith("PA-SX"):
        from .pa_sx_llm import create_pa_sx_llm
        config = _load_pa_model_config(PAModel(model_str))
        return create_pa_sx_llm(
            config,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            enable_thinking=enable_thinking,
            extra_body_override=extra_body,
        )

    return _create_openai_compat_model(
        model_str, temperature, max_tokens, streaming, api_key, base_url
    )


# ============ DeepSeek / OpenAI 兼容 ============


_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "deepseek-chat": {
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "deepseek-reasoner": {
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
    },
}


def _create_openai_compat_model(
    model_name: str,
    temperature: float,
    max_tokens: int,
    streaming: bool,
    api_key: str | None,
    base_url: str | None,
) -> "BaseChatModel":
    """创建 OpenAI 兼容模型（DeepSeek 等）。"""
    from langchain_openai import ChatOpenAI

    defaults = _PROVIDER_DEFAULTS.get(model_name, {})

    effective_base_url = base_url or defaults.get("base_url", "")
    effective_api_key = api_key
    if not effective_api_key:
        env_key = defaults.get("env_key", "")
        if env_key:
            effective_api_key = os.getenv(env_key, "")
    if not effective_api_key:
        raise ValueError(
            f"api_key is required for model '{model_name}'. "
            f"Pass it directly or set {defaults.get('env_key', 'API_KEY')} env var."
        )

    kwargs: dict[str, Any] = {
        "model": model_name,
        "api_key": effective_api_key,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "streaming": streaming,
    }
    if effective_base_url:
        kwargs["base_url"] = effective_base_url

    return ChatOpenAI(**kwargs)


# ============ 便捷函数 ============


def get_available_models() -> list[str]:
    """获取所有可用的模型名称"""
    return [m.value for m in PAModel] + list(_PROVIDER_DEFAULTS.keys())
