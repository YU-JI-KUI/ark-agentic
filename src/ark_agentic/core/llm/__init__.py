"""LLM Client: 统一工厂接口

统一入口 create_chat_model()，返回 BaseChatModel。
"""

from .factory import (
    PAModel,
    PAModelConfig,
    create_chat_model,
)

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
    # Errors
    "LLMErrorReason",
    "LLMError",
    "classify_error",
]
