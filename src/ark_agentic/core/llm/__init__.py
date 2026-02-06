"""
LLM Client 模块

提供统一的 LLM 调用接口，支持多种提供商：
- PA Internal LLM（默认，PA-JT-80B, PA-SX-80B, PA-SX-235B）
- DeepSeek (OpenAI 兼容)
- OpenAI
- 内部 API (internal, simple)

使用示例:
```python
from ark_agentic.core.llm import create_llm_client, PAModel

# 使用 PA Internal LLM（默认）
client = create_llm_client()

# 指定 PA 模型
client = create_llm_client("pa", pa_model=PAModel.PA_JT_80B)

# 使用 DeepSeek
client = create_llm_client("deepseek", api_key="sk-xxx")

# 调用（支持 thinking 参数，仅 JT 系列）
response = await client.chat(
    messages=[{"role": "user", "content": "你好"}],
    chat_template_kwargs={"enable_thinking": True, "thinking": True},
)
```
"""

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
    create_openai_client,
)

from .internal import (
    InternalAPIClient,
    SimpleInternalClient,
    create_internal_client,
    create_simple_client,
)

from .pa_internal_llm import (
    PAModel,
    PAInternalClient,
    create_pa_client,
)

from .factory import (
    create_llm_client,
    get_available_providers,
    check_api_key_available,
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
    "create_openai_client",
    # Internal
    "InternalAPIClient",
    "SimpleInternalClient",
    "create_internal_client",
    "create_simple_client",
    # PA Internal
    "PAModel",
    "PAInternalClient",
    "create_pa_client",
    # Factory
    "create_llm_client",
    "get_available_providers",
    "check_api_key_available",
]
