"""
LLM Client 工厂（ChatOpenAI 统一入口）

统一 PA 内部模型和 OpenAI 兼容模型的创建，返回 BaseChatModel。

模型分类：
1. OpenAI 兼容模型 — 标准 ChatOpenAI（API_KEY + LLM_BASE_URL）
2. PA 内部模型：
   A. PA-JT-*: JT transport（RSA + HMAC 签名 + body 注入）
   B. PA-SX-*: SX transport（trace headers + body 注入）

所有生成参数统一通过 SamplingConfig 传入，OpenAI 顶层与 vLLM/SGLang
extra_body 扩展通过 to_chat_openai_kwargs() / to_extra_body() 分层注入。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, TYPE_CHECKING

from .sampling import SamplingConfig

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
    api_key: str = ""
    trace_app_id: str = ""
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
    sampling: SamplingConfig | None = None,
    streaming: bool = False,
    api_key: str | None = None,
    base_url: str | None = None,
) -> "BaseChatModel":
    """创建 LangChain ChatOpenAI 实例，返回 BaseChatModel。

    Args:
        model: 模型名称。PA-JT-80B / PA-SX-80B / PA-SX-235B 或任意 OpenAI 兼容模型 id
        sampling: 采样配置（None 时使用 SamplingConfig.for_chat() 默认）
        streaming: 是否启用流式
        api_key: API Key（OpenAI 兼容端点需要；PA 模型从环境变量读取）
        base_url: API 端点（OpenAI 兼容端点需要；PA 模型从环境变量读取）

    Returns:
        BaseChatModel 实例（ChatOpenAI 子类）

    Examples:
        # PA-SX 默认对话配置
        llm = create_chat_model("PA-SX-80B")

        # 结构化抽取场景
        llm = create_chat_model("PA-SX-80B", sampling=SamplingConfig.for_extraction())

        # OpenAI 兼容 + 自定义温度
        llm = create_chat_model(
            "gpt-4o",
            sampling=SamplingConfig.for_chat(temperature=0.3),
            api_key="sk-xxx",
            base_url="https://api.openai.com/v1",
        )
    """
    model_str = model.value if isinstance(model, PAModel) else model
    sampling = sampling or SamplingConfig.for_chat()

    try:
        from langchain_openai import ChatOpenAI  # noqa: F401
    except ImportError as e:
        raise ImportError(
            f"langchain-openai is required. Install with: pip install langchain-openai. {e}"
        ) from e

    if model_str.startswith("PA-JT"):
        from .pa_jt_llm import create_pa_jt_llm
        config = _load_pa_model_config(PAModel(model_str))
        return create_pa_jt_llm(config, sampling=sampling, streaming=streaming)

    if model_str.startswith("PA-SX"):
        from .pa_sx_llm import create_pa_sx_llm
        config = _load_pa_model_config(PAModel(model_str))
        return create_pa_sx_llm(config, sampling=sampling, streaming=streaming)

    return _create_openai_compat_model(
        model_str,
        sampling=sampling,
        streaming=streaming,
        api_key=api_key,
        base_url=base_url,
    )


# ============ OpenAI 兼容 ============


def _resolve_api_key(api_key: str | None) -> str:
    """Resolve API key: argument > API_KEY env."""
    if api_key:
        return api_key
    return os.getenv("API_KEY", "")


def _create_openai_compat_model(
    model_name: str,
    *,
    sampling: SamplingConfig,
    streaming: bool,
    api_key: str | None,
    base_url: str | None,
) -> "BaseChatModel":
    """创建 OpenAI 兼容模型（API_KEY + LLM_BASE_URL）。"""
    from langchain_openai import ChatOpenAI
    from .debug_transport import make_debug_client

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
        "streaming": streaming,
        "http_async_client": make_debug_client(),
        "extra_body": sampling.to_extra_body(),
        **sampling.to_chat_openai_kwargs(),
    }
    if effective_base_url:
        kwargs["base_url"] = effective_base_url

    return ChatOpenAI(**kwargs)


# ============ 从环境创建 ============


def create_chat_model_from_env(
    *,
    sampling: SamplingConfig | None = None,
    streaming: bool = False,
) -> "BaseChatModel":
    """从环境变量创建 LLM。

    必填环境变量:
    - MODEL_NAME: 模型标识，如 PA-SX-80B、PA-JT-80B、gpt-4o 等
    - LLM_BASE_URL: 端点 URL（PA 时必填，OpenAI 兼容时可选）

    其他环境变量:
    - LLM_PROVIDER: pa | openai 等，默认 pa
    - API_KEY: OpenAI 兼容端点必填；PA-SX 端点鉴权用
    - PA-JT 签名专用: PA_JT_OPEN_API_CODE / PA_JT_RSA_PRIVATE_KEY 等
    - PA-SX trace 专用: PA_SX_80B_APP_ID / PA_SX_235B_APP_ID

    Args:
        sampling: 采样配置（None 时使用 SamplingConfig.for_chat() 默认）
        streaming: 是否启用流式
    """
    model_name_env = os.getenv("MODEL_NAME", "").strip()
    if not model_name_env:
        raise ValueError(
            "MODEL_NAME is required. Set MODEL_NAME env var (e.g. PA-SX-80B, gpt-4o)."
        )

    provider = os.getenv("LLM_PROVIDER", "pa").lower()

    if provider == "pa":
        try:
            pa_model = PAModel(model_name_env)
        except ValueError:
            raise ValueError(
                f"Invalid MODEL_NAME={model_name_env!r} for LLM_PROVIDER=pa. "
                f"Valid values: {[m.value for m in PAModel]}"
            )
        return create_chat_model(model=pa_model, sampling=sampling, streaming=streaming)

    api_key = _resolve_api_key(None)
    if not api_key:
        raise ValueError(
            f"API_KEY is required for LLM_PROVIDER={provider!r}. Set API_KEY env var."
        )
    base_url = os.getenv("LLM_BASE_URL", "").strip() or None
    return create_chat_model(
        model=model_name_env,
        api_key=api_key,
        base_url=base_url,
        sampling=sampling,
        streaming=streaming,
    )


# ============ 便捷函数 ============


def get_available_models() -> list[str]:
    """获取 PA 模型名称；OpenAI 兼容端点可使用任意模型 id。"""
    return [m.value for m in PAModel]
