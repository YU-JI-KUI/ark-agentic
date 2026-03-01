"""具体标的详情工具"""

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
        args = dict(tool_call.arguments or {})
        context = _normalize_context(context)
        security_code = args.get("security_code", "")
        # 优先 context，其次 args，最后 default
        context_account_type = context.get("account_type")
        account_type = args.get("account_type") or context_account_type or "normal"
        user_id = context.get("user_id", "U001")
        
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
