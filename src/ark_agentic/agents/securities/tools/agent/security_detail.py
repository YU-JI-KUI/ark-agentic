"""具体标的详情工具

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

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_string_param
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


class SecurityDetailTool(AgentTool):
    """查询具体标的详情"""

    name = "security_detail"
    description = "查询具体标的（股票、基金、ETF）的持仓和行情信息"
    thinking_hint = "正在查询持仓行情…"
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


    async def execute(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        args = tool_call.arguments or {}
        context = context or {}

        security_code = read_string_param(args, "security_code", "")

        # 参数优先级：tool args > user:* context > 裸 key context > 默认值
        account_type = args.get("account_type") or _get_context_value(
            context, "account_type", "normal"
        )
        user_id = _get_context_value(context, "id") or _get_context_value(
            context, "user_id", "U001"
        )

        try:
            data = await create_service_adapter("security_detail", context=context).call(
                account_type=account_type,
                user_id=user_id,
                security_code=security_code,
                _context=context,
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
