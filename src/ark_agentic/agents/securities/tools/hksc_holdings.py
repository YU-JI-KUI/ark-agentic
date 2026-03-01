"""港股通持仓工具"""

from __future__ import annotations

import os
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

from .service_client import create_service_adapter


def _normalize_context(context: dict[str, Any] | None) -> dict[str, Any]:
    """标准化 context，兼容 user: 前缀与旧键名。"""
    raw = context or {}
    normalized = dict(raw)

    for key, value in raw.items():
        if key.startswith("user:"):
            plain_key = key.split(":", 1)[1]
            normalized.setdefault(plain_key, value)

    if "id" in normalized:
        normalized.setdefault("user_id", normalized["id"])

    return normalized


class HKSCHoldingsTool(AgentTool):
    """查询港股通持仓信息"""
    
    name = "hksc_holdings"
    description = "查询用户的港股通持仓信息，包括持仓列表、成本、市值、盈亏等"
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
            "hksc_holdings",
            mock=os.getenv("SECURITIES_SERVICE_MOCK", "").lower() in ("true", "1"),
        )
    
    async def execute(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        args = dict(tool_call.arguments or {})
        context = _normalize_context(context)

        # 上下文中的参数优先级高于 args
        args.update(context)
        
        # HKSC 不区分账户类型，但仍保留参数兼容
        account_type = args.get("account_type") or context.get("account_type", "normal")
        user_id = context.get("user_id", "U001")
        
        try:
            # 传递完整 context 给 adapter（用于参数映射和 header 认证）
            data = await self._adapter.call(
                account_type=account_type,
                user_id=user_id,
                _context=context,  # 传递完整上下文
            )
            state_delta = {self.name: data}
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data=data,
                metadata={"state_delta": state_delta}
            )
        except Exception as e:
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error=str(e),
            )
