"""账户总资产工具"""

from __future__ import annotations

import os
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

from .service_client import create_service_adapter


class AccountOverviewTool(AgentTool):
    """查询账户总资产信息"""
    
    name = "account_overview"
    description = "查询用户账户的总资产信息，包括总资产、现金、股票市值、今日收益等。支持普通账户和两融账户。"
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
            "account_overview",
            mock=os.getenv("SECURITIES_SERVICE_MOCK", "").lower() in ("true", "1"),
        )
    
    async def execute(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        args = tool_call.arguments
        # 优先从 args 获取（LLM 显式指定），其次从 context 获取，最后默认为 normal
        # 注意：通常 LLM 不会指定 account_type，而是由系统上下文决定
        context_account_type = context.get("account_type") if context else None
        account_type = args.get("account_type") or context_account_type or "normal"
        
        # 从上下文获取用户信息
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
