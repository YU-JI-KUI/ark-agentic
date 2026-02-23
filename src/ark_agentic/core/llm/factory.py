"""
LLM Client 工厂（ChatOpenAI 统一入口）

统一 PA 内部模型和 OpenAI 兼容模型的创建。

模型分类：
1. DeepSeek 等 OpenAI 兼容模型 — 标准 ChatOpenAI
2. PA 内部模型：
   A. PA-JT-*: 需要 PinganEAGWHeaderAsyncTransport（RSA + HMAC 签名）
   B. PA-SX-*: 使用固定 header（Bearer token + trace headers）

旧的 create_llm_client() / PAInternalClient 标记为废弃，
新代码统一使用 create_chat_model()。

所有返回的 ChatOpenAI 实例都通过 LangChainLLMProtocol 包装，
以恢复依赖倒置并提供类型安全。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

import httpx

from .protocol import LangChainLLMProtocol, wrap_chat_openai

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
    return PAModelConfig(
        base_url=base_url,
        model_name=model.value,
        model_type="sx",
        api_key=os.getenv("PA_SX_API_KEY", ""),
        trace_app_id=os.getenv(app_id_env, ""),
    )


# ============ ChatOpenAI 工厂 ============


def create_chat_model(
    model: str | PAModel = "PA-SX-80B",
    *,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    streaming: bool = False,
    # DeepSeek / OpenAI 兼容专用
    api_key: str | None = None,
    base_url: str | None = None,
    # 额外参数（允许调用方覆盖 extra_body 中的值，如 chat_template_kwargs）
    extra_body: dict[str, Any] | None = None,
) -> LangChainLLMProtocol:
    """创建 langchain ChatOpenAI 实例，失败时抛出异常。

    Args:
        model: 模型名称。PA-JT-80B / PA-SX-80B / PA-SX-235B / deepseek-chat / 其他
        temperature: 温度
        max_tokens: 最大 token
        streaming: 是否启用流式
        api_key: API Key（DeepSeek 等需要；PA 模型从环境变量读取）
        base_url: API 端点（DeepSeek 等需要；PA 模型从环境变量读取）
        extra_body: 额外 body 参数，会合并到默认值之上（可覆盖 chat_template_kwargs 等）

    Returns:
        ChatOpenAI 实例（包装为 LangChainLLMProtocol）

    Examples:
        # PA-SX（默认）
        llm = create_chat_model("PA-SX-80B")

        # PA-JT（需要网关签名）
        llm = create_chat_model("PA-JT-80B")

        # DeepSeek
        llm = create_chat_model("deepseek-chat", api_key="sk-xxx")
    """
    # 解析模型类型
    model_str = model.value if isinstance(model, PAModel) else model

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise ImportError(
            f"langchain-openai is required for create_chat_model. Install with: pip install langchain-openai. {e}"
        ) from e

    if model_str.startswith("PA-JT"):
        return _create_pa_jt_model(
            model_str, temperature, max_tokens, streaming, extra_body
        )
    elif model_str.startswith("PA-SX"):
        return _create_pa_sx_model(model_str, temperature, max_tokens, streaming)
    else:
        return _create_openai_compat_model(
            model_str, temperature, max_tokens, streaming, api_key, base_url
        )


# ============ PA-JT：需要 Transport ============


def _create_pa_jt_model(
    model_name: str,
    temperature: float,
    max_tokens: int,
    streaming: bool,
    extra_body_override: dict[str, Any] | None = None,
) -> LangChainLLMProtocol:
    """创建 PA-JT 系列模型（使用 PinganEAGWHeaderAsyncTransport）。

    Raises:
        ImportError: 如果 pycryptodome 未安装
        ValueError: 如果必需的环境变量缺失
    """
    import uuid as _uuid

    from langchain_openai import ChatOpenAI

    try:
        from .transport import PinganEAGWHeaderAsyncTransport
    except ImportError as e:
        logger.warning(
            f"PA-JT models require pycryptodome for RSA signing. "
            f"Install with: uv add 'ark-agentic[pa-jt]' or uv add pycryptodome. "
            f"Error: {e}"
        )
        # Re-raise to let main create_chat_model handle graceful fallback
        raise

    pa_model = PAModel(model_name)
    config = _load_pa_model_config(pa_model)

    try:
        transport = PinganEAGWHeaderAsyncTransport(
            base_transport=httpx.AsyncHTTPTransport(retries=3),
            api_code=config.open_api_code,
            gateway_credential=config.open_api_credential,
            gateway_key=config.rsa_private_key,
            app_key=config.gpt_app_key,
            app_secret=config.gpt_app_secret,
            scene_id=config.scene_id,
        )
    except ImportError as e:
        logger.warning(
            f"PA-JT models require pycryptodome for RSA signing. "
            f"Install with: uv add 'ark-agentic[pa-jt]' or uv add pycryptodome. "
            f"Error: {e}"
        )
        # Re-raise to let main create_chat_model handle graceful fallback
        raise

    http_async_client = httpx.AsyncClient(transport=transport)
    logger.info(f"ChatOpenAI: PA-JT transport enabled for {model_name}")

    # 构建 extra_body（默认值 + 调用方覆盖）
    jt_extra_body: dict[str, Any] = {
        "request_id": _uuid.uuid4().hex,
        "scene_id": config.scene_id,
        "seed": 42,
        "chat_template_kwargs": {
            "enable_thinking": False,
            "thinking": False,
        },
    }
    if extra_body_override:
        jt_extra_body.update(extra_body_override)

    chat_openai = ChatOpenAI(
        base_url=config.base_url,
        api_key="EMPTY",  # JT 使用网关签名，无需 API Key
        model=config.model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
        http_async_client=http_async_client,
        extra_body=jt_extra_body,
    )

    return wrap_chat_openai(chat_openai)


# ============ PA-SX：固定 Header ============


def _create_pa_sx_model(
    model_name: str,
    temperature: float,
    max_tokens: int,
    streaming: bool,
) -> LangChainLLMProtocol:
    """创建 PA-SX 系列模型（使用固定 Bearer token + trace headers）。"""
    from langchain_openai import ChatOpenAI

    pa_model = PAModel(model_name)
    config = _load_pa_model_config(pa_model)

    # SX 模型通过固定 header 鉴权
    default_headers = {
        "trace-appId": config.trace_app_id,
        "trace-source": "",
        "trace-userId": "",
    }

    logger.info(f"ChatOpenAI: PA-SX model {model_name} with trace headers")

    chat_openai = ChatOpenAI(
        base_url=config.base_url,
        api_key=config.api_key or "EMPTY",
        model=config.model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
        default_headers=default_headers,
    )

    return wrap_chat_openai(chat_openai)


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
) -> LangChainLLMProtocol:
    """创建 OpenAI 兼容模型（DeepSeek 等）。"""
    from langchain_openai import ChatOpenAI

    # 从预设或环境变量解析配置
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

    chat_openai = ChatOpenAI(**kwargs)
    return wrap_chat_openai(chat_openai)


# ============ 便捷函数 ============


def get_available_models() -> list[str]:
    """获取所有可用的模型名称"""
    return [m.value for m in PAModel] + list(_PROVIDER_DEFAULTS.keys())
