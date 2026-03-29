"""LLM Client: 统一工厂接口

统一入口 create_chat_model()，返回 BaseChatModel。
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

__all__ = [
    # Factory
    "PAModel",
    "PAModelConfig",
    "create_chat_model",
    "create_chat_model_from_env",
    # Caller
    "LLMCaller",
    # Errors
    "LLMErrorReason",
    "LLMError",
    "classify_error",
]
