"""
LLM Client 工厂（ChatOpenAI 统一入口）

统一 PA 内部模型和 OpenAI 兼容模型的创建，返回 BaseChatModel。

模型分类：
1. OpenAI 兼容模型 — 标准 ChatOpenAI（API_KEY + LLM_BASE_URL）
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

    公共变量: LLM_BASE_URL（PA-JT/PA-SX 共用）、API_KEY（PA-SX 鉴权）
    PA-JT 签名专用: PA_JT_OPEN_API_CODE、PA_JT_OPEN_API_CREDENTIAL、
                   PA_JT_RSA_PRIVATE_KEY、PA_JT_GPT_APP_KEY、
                   PA_JT_GPT_APP_SECRET、PA_JT_SCENE_ID
    PA-SX trace 专用: PA_SX_80B_APP_ID、PA_SX_235B_APP_ID

    Raises:
        ValueError: 如果必需的环境变量缺失
    """
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    if not base_url:
        raise ValueError(
            "LLM_BASE_URL is required for PA models. "
            "Please set it in your .env file."
        )

    if model == PAModel.PA_JT_80B:
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
    app_id_env = (
        "PA_SX_80B_APP_ID" if model == PAModel.PA_SX_80B else "PA_SX_235B_APP_ID"
    )
    return PAModelConfig(
        base_url=base_url,
        model_name=model.value,
        model_type="sx",
        api_key=os.getenv("API_KEY", ""),
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
    # OpenAI 兼容专用
    api_key: str | None = None,
    base_url: str | None = None,
    # 额外参数（PA 模型：合并进 ChatOpenAI.extra_body）
    extra_body: dict[str, Any] | None = None,
) -> "BaseChatModel":
    """创建 LangChain ChatOpenAI 实例，返回 BaseChatModel。

    Args:
        model: 模型名称。PA-JT-80B / PA-SX-80B / PA-SX-235B 或任意 OpenAI 兼容模型 id
        temperature: 温度
        max_tokens: 最大 token
        streaming: 是否启用流式
        enable_thinking: 是否启用 thinking
        api_key: API Key（OpenAI 兼容端点需要；PA 模型从环境变量读取）
        base_url: API 端点（OpenAI 兼容端点需要；PA 模型从环境变量读取）
        extra_body: 额外 body 字段，合并进 ChatOpenAI.extra_body（PA 模型）

    Returns:
        BaseChatModel 实例（ChatOpenAI 子类）

    Examples:
        # PA-SX（默认）
        llm = create_chat_model("PA-SX-80B")

        # PA-JT（需要网关签名）
        llm = create_chat_model("PA-JT-80B")

        # OpenAI 兼容
        llm = create_chat_model("gpt-4o", api_key="sk-xxx", base_url="https://api.openai.com/v1")
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


# ============ OpenAI 兼容 ============


def _resolve_api_key(api_key: str | None) -> str:
    """Resolve API key: argument > API_KEY env."""
    if api_key:
        return api_key
    return os.getenv("API_KEY", "")


def _create_openai_compat_model(
    model_name: str,
    temperature: float,
    max_tokens: int,
    streaming: bool,
    api_key: str | None,
    base_url: str | None,
) -> "BaseChatModel":
    """创建 OpenAI 兼容模型（API_KEY + LLM_BASE_URL）。"""
    from langchain_openai import ChatOpenAI

    effective_base_url = (base_url or os.getenv("LLM_BASE_URL", "") or "").strip()
    effective_api_key = _resolve_api_key(api_key)
    if not effective_api_key:
        raise ValueError(
            f"api_key is required for model '{model_name}'. "
            "Pass it directly or set API_KEY env var."
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


# ============ 从环境创建 ============


def create_chat_model_from_env(
    *,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    streaming: bool = False,
) -> "BaseChatModel":
    """从环境变量创建 LLM。仅从环境读取，无覆盖参数。

    必填环境变量:
    - MODEL_NAME: 模型标识，如 PA-SX-80B、PA-JT-80B、gpt-4o 等（未设置则报错）
    - LLM_BASE_URL: 端点 URL（PA 和 OpenAI 兼容共用；PA 时必填，OpenAI 兼容时可选）

    其他环境变量:
    - LLM_PROVIDER: pa | openai 等，默认 pa
    - API_KEY: OpenAI 兼容端点必填；PA-SX 端点鉴权用
    - PA-JT 签名专用: PA_JT_OPEN_API_CODE / PA_JT_RSA_PRIVATE_KEY 等
    - PA-SX trace 专用: PA_SX_80B_APP_ID / PA_SX_235B_APP_ID
    """
    model_name_env = os.getenv("MODEL_NAME", "").strip()
    if not model_name_env:
        raise ValueError(
            "MODEL_NAME is required. Set MODEL_NAME env var (e.g. PA-SX-80B, gpt-4o)."
        )

    provider = os.getenv("LLM_PROVIDER", "pa").lower()
    api_key = _resolve_api_key(None)
    base_url = os.getenv("LLM_BASE_URL", "").strip() or None

    if provider == "pa":
        try:
            pa_model = PAModel(model_name_env)
        except ValueError:
            raise ValueError(
                f"Invalid MODEL_NAME={model_name_env!r} for LLM_PROVIDER=pa. "
                f"Valid values: {[m.value for m in PAModel]}"
            )
        return create_chat_model(model=pa_model)
    # OpenAI-compatible path
    if not api_key:
        raise ValueError(
            "LLM_PROVIDER is not 'pa' and no API key found. Set API_KEY or use LLM_PROVIDER=pa."
        )
    return create_chat_model(
        model=model_name_env,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
    )


# ============ 便捷函数 ============


def get_available_models() -> list[str]:
    """获取 PA 模型名称；OpenAI 兼容端点可使用任意模型 id，由 MODEL_NAME/LLM_BASE_URL 指定。"""
    return [m.value for m in PAModel]
