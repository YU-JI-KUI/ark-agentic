"""现金资产工具

从扁平 context 获取参数：
- token_id: 用户令牌（必需，由前端传入）
- account_type: 账户类型，normal 或 margin（可选，默认 normal）
- user_id: 用户 ID（可选）
"""

from __future__ import annotations

import os
from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

from .service_client import create_service_adapter


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
        args = tool_call.arguments
        context = context or {}
        # 上下文中的参数优先级高于 args，例如用户令牌或账户切换等信息。
        args.update(context)
        
        # 从扁平 context 获取业务参数
        # 优先级: args > context > 默认值
        account_type = args.get("account_type") or context.get("account_type", "normal")
        user_id = context.get("user_id", "U001")
        
        try:
            # 传递完整 context 给 adapter（用于参数映射）
            data = await self._adapter.call(
                account_type=account_type,
                user_id=user_id,
                _context=context,  # 传递完整上下文供参数映射使用
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
