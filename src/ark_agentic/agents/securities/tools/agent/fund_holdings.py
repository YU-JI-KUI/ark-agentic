"""基金理财持仓工具

从 context 获取参数（支持 user: 前缀和裸 key 兼容）：

**validatedata 必需字段**（生产环境必需，Mock 模式可省略）：
- channel: 渠道类型（如 REST），key: user:channel 或 channel
- usercode: 用户代码，key: user:usercode 或 usercode
- userid: 用户ID，key: user:userid 或 userid
- account: 账户号，key: user:account 或 account
- branchno: 分支机构号，key: user:branchno 或 branchno
- loginflag: 登录标志，key: user:loginflag 或 loginflag
- mobileNo: 手机号，key: user:mobileNo 或 mobileNo

**signature 必需字段**：
- signature: 签名字符串（生产环境必需），key: user:signature 或 signature

**其他可选字段**：
- account_type: 账户类型，normal 或 margin（可选，默认 normal，key: user:account_type 或 account_type）
- user_id: 用户 ID（可选，key: user:id 或 user_id）
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolCall

from ..service import create_service_adapter


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
    thinking_hint = "正在查询基金持仓…"
    parameters = [
        ToolParameter(
            name="account_type",
            type="string",
            description="账户类型：normal（普通账户）或 margin（两融账户），默认为 normal",
            required=False,
        ),
    ]


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

        if account_type == "margin":
            error_data = {"_error": "margin_not_supported", "account_type": "margin"}
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data={"message": "两融账户不支持查询基金持仓，请调用 render_a2ui 展示提示卡片。"},
                metadata={"state_delta": {self.name: error_data}},
            )

        try:
            data = await create_service_adapter("fund_holdings", context=context).call(
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
