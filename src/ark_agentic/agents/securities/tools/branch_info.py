"""开户营业部查询工具

从 context 获取认证参数（支持 user: 前缀和裸 key 兼容）：

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
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.tools.base import AgentTool
from ark_agentic.core.types import AgentToolResult, ToolCall

from .service_client import create_service_adapter


class BranchInfoTool(AgentTool):
    """查询用户开户营业部信息"""

    name = "branch_info"
    description = "查询用户的开户营业部信息，包括营业部名称、地址、联系电话及席位号"
    thinking_hint = "正在查询开户营业部…"
    parameters = []


    async def execute(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        context = context or {}

        try:
            data = await create_service_adapter("branch_info", context=context).call(
                account_type="normal",
                user_id="",
                _context=context,
            )

            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data=data,
                metadata={"state_delta": {self.name: data}},
            )
        except Exception as e:
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error=str(e),
            )
