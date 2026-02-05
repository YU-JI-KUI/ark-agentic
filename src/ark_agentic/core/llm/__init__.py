"""
LLM Client 模块

提供统一的 LLM 调用接口，支持多种提供商：
- DeepSeek (OpenAI 兼容)
- Gemini (OpenAI 兼容)
- OpenAI
- 内部 API (internal, unified, simple)

使用示例:
```python
from ark_agentic.core.llm import create_llm_client

# 使用 DeepSeek
client = create_llm_client("deepseek", api_key="sk-xxx")

# 使用 Gemini
client = create_llm_client("gemini", api_key="xxx")

# 使用内部 API
client = create_llm_client(
    "internal",
    base_url="http://internal-api.example.com/chat",
    authorization="Bearer xxx",
    trace_appid="my-app",
)

# 使用 Unified 内部 API
client = create_llm_client(
    "unified",
    base_url="https://my-llm/api-app/agent/unified/v1/chat/completions",
    authorization="Bearer sk-xxxxx",
    trace_appid="my-app",
    trace_source="ark-agentic",
    trace_user_id="user123",
)

# 使用 Simple 内部 API
client = create_llm_client(
    "simple",
    base_url="https://my-llm/simple-api",
)

# 调用
response = await client.chat(
    messages=[{"role": "user", "content": "Hello!"}],
    temperature=0.7,
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
)

from .openai_compat import (
    OpenAICompatibleClient,
    create_deepseek_client,
    create_gemini_client,
    create_openai_client,
)

from .internal import (
    InternalAPIClient,
    UnifiedInternalClient,
    SimpleInternalClient,
    create_internal_client,
    create_unified_client,
    create_simple_client,
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
    # OpenAI Compatible
    "OpenAICompatibleClient",
    "create_deepseek_client",
    "create_gemini_client",
    "create_openai_client",
    # Internal
    "InternalAPIClient",
    "UnifiedInternalClient",
    "SimpleInternalClient",
    "create_internal_client",
    "create_unified_client",
    "create_simple_client",
    # Factory
    "create_llm_client",
    "get_available_providers",
    "check_api_key_available",
]
