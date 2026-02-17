"""港股通持仓工具"""

from __future__ import annotations

import os
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

from .service_client import create_service_adapter


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
        args = tool_call.arguments
        # 优先 context，其次 args，最后 default
        context_account_type = context.get("account_type") if context else None
        account_type = args.get("account_type") or context_account_type or "normal"
        user_id = context.get("user_id", "U001") if context else "U001"
        
        try:
            data = await self._adapter.call(
                account_type=account_type,
                user_id=user_id,
            )
            
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data=data,
            )
        except Exception as e:
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error=str(e),
            )
