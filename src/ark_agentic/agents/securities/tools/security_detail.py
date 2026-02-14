"""具体标的详情工具"""

from __future__ import annotations

import os
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

from .service_client import create_service_adapter


class SecurityDetailTool(AgentTool):
    """查询具体标的详情"""
    
    name = "security_detail"
    description = "查询具体标的（股票、基金、ETF）的持仓和行情信息"
    parameters = [
        ToolParameter(
            name="security_code",
            type="string",
            description="证券代码，如 510300、00700 等",
            required=True,
        ),
        ToolParameter(
            name="account_type",
            type="string",
            description="账户类型：normal（普通账户）或 margin（两融账户），默认为 normal",
            required=False,
        ),
    ]
    
    def __init__(self):
        self._adapter = create_service_adapter(
            "security_detail",
            mock=os.getenv("SECURITIES_SERVICE_MOCK", "").lower() in ("true", "1"),
        )
    
    async def execute(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        args = tool_call.arguments
        security_code = args.get("security_code")
        
        if not security_code:
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error="Missing required parameter: security_code",
            )
        
        account_type = args.get("account_type", "normal")
        user_id = context.get("user_id", "U001") if context else "U001"
        
        try:
            data = await self._adapter.call(
                account_type=account_type,
                user_id=user_id,
                security_code=security_code,
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
