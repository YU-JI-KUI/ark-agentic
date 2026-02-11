"""LLM Client: PA/DeepSeek/OpenAI 统一接口"""

from .base import (
    LLMClientProtocol,
    LLMConfig,
    LLMUsage,
    LLMToolCall,
    LLMMessage,
    LLMChoice,
    LLMResponse,
    BaseLLMClient,
    DynamicValues,
)

from .openai_compat import (
    OpenAICompatibleClient,
    create_deepseek_client,
)

from .pa_internal_llm import (
    PAModel,
    PAInternalClient,
    create_pa_client,
)

from .mock import (
    MockLLMClient,
    create_mock_client,
)

from .factory import (
    create_llm_client,
    get_available_providers,
    check_api_key_available,
)

from .errors import (
    LLMErrorReason,
    LLMError,
    classify_error,
    FallbackLLMClient,
    FallbackModelConfig,
)

__all__ = [
    # Base
    "LLMClientProtocol",
    "LLMConfig",
    "LLMUsage",
    "LLMToolCall",
    "LLMMessage",
    "LLMChoice",
    "LLMResponse",
    "BaseLLMClient",
    "DynamicValues",
    # OpenAI Compatible
    "OpenAICompatibleClient",
    "create_deepseek_client",
    # PA Internal
    "PAModel",
    "PAInternalClient",
    "create_pa_client",
    # Mock
    "MockLLMClient",
    "create_mock_client",
    # Factory
    "create_llm_client",
    "get_available_providers",
    "check_api_key_available",
    # Errors & Fallback
    "LLMErrorReason",
    "LLMError",
    "classify_error",
    "FallbackLLMClient",
    "FallbackModelConfig",
]
