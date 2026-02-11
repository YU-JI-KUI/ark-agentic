"""
Mock LLM Client

用于演示和测试，不依赖真实 API。
模拟保险取款场景的完整对话流程。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from .base import BaseLLMClient, LLMConfig

logger = logging.getLogger(__name__)


class MockLLMClient(BaseLLMClient):
    """模拟 LLM 客户端

    用于演示和测试，不依赖真实 API。
    模拟完整的工具调用和对话流程。

    特性：
    - 无需 API Key 或网络连接
    - 预设的响应逻辑（工具调用 → 方案推荐 → 后续对话）
    - 兼容 LLMClientProtocol 接口
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        """初始化 Mock 客户端

        Args:
            config: LLM 配置（可选，Mock 客户端不需要配置）
        """
        if config is None:
            config = LLMConfig(provider="mock", api_key="", base_url="", model="mock-model")
        super().__init__(config)
        self._call_count = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        """模拟聊天响应

        Args:
            messages: 消息列表
            tools: 工具定义列表
            stream: 是否流式输出（暂不支持）
            **kwargs: 其他参数

        Returns:
            模拟的响应字典
        """
        if stream:
            logger.warning("Mock client does not support streaming, returning non-stream response")

        self._call_count += 1

        # 获取用户最后一条消息
        user_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break

        # 检查是否有工具结果
        has_tool_results = any(msg.get("role") == "tool" for msg in messages)

        # 根据对话阶段返回不同响应
        if self._call_count == 1 and not has_tool_results:
            return self._response_with_tools()
        elif has_tool_results and self._call_count <= 2:
            return self._response_with_plans()
        else:
            return self._response_followup(user_message)

    def _response_with_tools(self) -> dict[str, Any]:
        """返回带工具调用的响应"""
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_001",
                                "type": "function",
                                "function": {
                                    "name": "policy_query",
                                    "arguments": '{"user_id": "U001", "query_type": "list"}',
                                },
                            },
                            {
                                "id": "call_002",
                                "type": "function",
                                "function": {
                                    "name": "policy_query",
                                    "arguments": '{"user_id": "U001", "query_type": "withdrawal_limit"}',
                                },
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }

    def _response_with_plans(self) -> dict[str, Any]:
        """返回推荐方案"""
        content = """好的，张先生，我已经查询了您的保单信息。根据您的情况，我为您推荐以下取款方案：

## 推荐方案

### 方案一：部分领取 ⭐ 推荐

从您的「金瑞人生年金险」中部分领取：

- 💰 **可领取金额**：65,000元
- ⏱️ **到账时间**：3-5个工作日
- 💵 **费用**：无手续费
- 💡 **特点**：不影响保单其他权益

**推荐理由**：无利息成本，操作简单，适合短期资金需求。

---

### 方案二：保单贷款

从您的「平安福终身寿险」中申请贷款：

- 💰 **可贷金额**：33,600元
- ⏱️ **到账时间**：1-2个工作日
- 💵 **年利息**：约1,848元（年利率5.5%）
- 💡 **特点**：保障不变，可随时还款

**推荐理由**：到账最快，保障完全不受影响，适合短期周转。

---

### 方案三：组合方案

同时使用以上两种方式：

- 💰 **合计可取**：98,600元
- 💡 **特点**：获取最大资金额度

---

请问您倾向于哪个方案？或者您需要的金额是多少，我可以帮您做更精确的计算。"""

        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ]
        }

    def _response_followup(self, user_message: str) -> dict[str, Any]:
        """返回后续对话响应"""
        if "方案一" in user_message or "部分领取" in user_message:
            content = """好的，您选择了**部分领取**方案。

我来为您确认一下操作细节：

📋 **操作确认**
- 保单：金瑞人生年金险（POL002）
- 操作：部分领取
- 金额：65,000元
- 到账：3-5个工作日

⚠️ **温馨提示**
- 领取后账户价值将相应减少
- 未来年金领取金额会略有调整

如果确认无误，您可以通过以下方式办理：
1. APP自助办理（推荐）
2. 拨打客服热线 95511
3. 前往就近营业网点

请问还有其他问题吗？"""
        else:
            content = """好的，我明白了。还有什么我可以帮您的吗？

如果您想了解更多方案细节，或者有其他保险问题，随时告诉我。"""

        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ]
        }


# ============ 便捷函数 ============


def create_mock_client(**kwargs: Any) -> MockLLMClient:
    """创建 Mock 客户端

    Args:
        **kwargs: 额外配置参数（Mock 客户端会忽略大部分配置）

    Returns:
        MockLLMClient 实例

    Examples:
        # 创建 Mock 客户端
        client = create_mock_client()

        # 或通过工厂函数
        from ark_agentic.core.llm import create_llm_client
        client = create_llm_client("mock")
    """
    config = LLMConfig(provider="mock", api_key="", base_url="", model="mock-model", **kwargs)
    return MockLLMClient(config)
