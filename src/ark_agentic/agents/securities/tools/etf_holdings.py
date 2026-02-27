"""ETF 持仓工具

从扁平 context 获取参数：
- validatedata: ETF API 认证数据（可选，真实 API 需要）
- signature: ETF API 签名（可选，真实 API 需要）
- asset_grp_type: 资产组类型，默认 7 表示 ETF（可选）
- limit: 返回条数限制，默认 20（可选）
- account_type: 账户类型（可选，ETF 不区分账户类型）
- user_id: 用户 ID（可选）
"""

from __future__ import annotations

import os
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

from .service_client import create_service_adapter


class ETFHoldingsTool(AgentTool):
    """查询 ETF 持仓信息"""
    
    name = "etf_holdings"
    description = "查询用户的 ETF 持仓信息，包括持仓列表、市值、今日收益等。ETF 持仓不区分普通账户和两融账户。"
    parameters = [
        ToolParameter(
            name="account_type",
            type="string",
            description="账户类型：normal（普通账户）或 margin（两融账户），默认为 normal。注意：ETF 持仓查询不区分账户类型。",
            required=False,
        ),
    ]
    
    def __init__(self):
        self._adapter = create_service_adapter(
            "etf_holdings",
            mock=os.getenv("SECURITIES_SERVICE_MOCK", "").lower() in ("true", "1"),
        )
    
    async def execute(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        args = tool_call.arguments
        context = context or {}
        
        # 上下文中的参数优先级高于 args
        args.update(context)
        
        # ETF 不区分账户类型，但仍保留参数兼容
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
