"""基金理财持仓工具

从 context 获取参数（支持 user: 前缀和裸 key 兼容）：
- token_id: 用户令牌（可选）
- account_type: 账户类型，normal 或 margin（可选，默认 normal，key: user:account_type 或 account_type）
- user_id: 用户 ID（可选，key: user:id 或 user_id）
"""

from __future__ import annotations

import os
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

from .service_client import create_service_adapter


def _get_context_value(
    context: dict[str, Any] | None, key: str, default: Any = None
) -> Any:
    """从 context 获取值，优先 user: 前缀，兼容裸 key"""
    if context is None:
        return default
    prefixed = f"user:{key}"
    if prefixed in context:
        return context[prefixed]
    if key in context:
        return context[key]
    return default


class FundHoldingsTool(AgentTool):
    """查询基金理财持仓信息"""

    name = "fund_holdings"
    description = "查询用户的基金理财产品持仓信息，包括持仓列表、成本、市值、盈亏等"
    parameters = [
        ToolParameter(
            name="account_type",
            type="string",
            description="账户类型：normal（普通账户）或 margin（两融账户），默认为 normal",
            required=False,
        ),
    ]

    def __init__(self):
        self._adapter = create_service_adapter(
            "fund_holdings",
            mock=os.getenv("SECURITIES_SERVICE_MOCK", "").lower() in ("true", "1"),
        )

    async def execute(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        args = tool_call.arguments or {}
        context = context or {}

        # 上下文参数来自客户端传入，优先级高于模型工具调用参数：user:* context > 裸 key context > tool args
        account_type = _get_context_value(
            context, "account_type", args.get("account_type") 
        )
        user_id = _get_context_value(context, "id") or _get_context_value(
            context, "user_id", "U001"
        )

        try:
            data = await self._adapter.call(
                account_type=account_type,
                user_id=user_id,
                _context=context,  # 传递完整上下文
            )

            state_delta = {self.name: data}
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data=data,
                metadata={"state_delta": state_delta},
            )
        except Exception as e:
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error=str(e),
            )
