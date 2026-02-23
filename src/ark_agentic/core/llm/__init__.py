"""LLM Client: 统一工厂接口

新的统一入口为 create_chat_model()，返回 ChatOpenAI 实例。
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

from .protocol import (
    LangChainLLMProtocol,
    ChatOpenAIWrapper,
    wrap_chat_openai,
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
    # Protocol
    "LangChainLLMProtocol",
    "ChatOpenAIWrapper",
    "wrap_chat_openai",
]
