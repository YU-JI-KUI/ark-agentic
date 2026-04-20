"""LLM Client: 统一工厂接口

统一入口 create_chat_model()，返回 BaseChatModel。
采样参数通过 SamplingConfig 收敛；重试通过 with_retry / with_retry_iterator。
"""

from .factory import (
    PAModel,
    PAModelConfig,
    create_chat_model,
    create_chat_model_from_env,
)

from .caller import LLMCaller

from .errors import (
    LLMErrorReason,
    LLMError,
    classify_error,
)

from .sampling import SamplingConfig

from .retry import with_retry, with_retry_iterator

__all__ = [
    "PAModel",
    "PAModelConfig",
    "create_chat_model",
    "create_chat_model_from_env",
    "LLMCaller",
    "LLMErrorReason",
    "LLMError",
    "classify_error",
    "SamplingConfig",
    "with_retry",
    "with_retry_iterator",
]
