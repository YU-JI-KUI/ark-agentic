"""现金资产工具

从 context 获取参数（支持 user: 前缀和裸 key 兼容）：
- token_id: 用户令牌（必需，由前端传入，key: user:token_id 或 token_id）
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


class CashAssetsTool(AgentTool):
    """查询现金资产信息"""

    name = "cash_assets"
    description = "查询用户的现金资产信息，包括现金总额、可用资金、可取资金、今日收益、冻结资金等。支持普通账户和两融账户。"
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
            "cash_assets",
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
            # 传递完整 context 给 adapter（用于参数映射）
            data = await self._adapter.call(
                account_type=account_type,
                user_id=user_id,
                _context=context,  # 传递完整上下文供参数映射使用
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
