"""SecurityInfoSearchTool：股票信息查询工具

通过 6 位股票代码或股票名称（含模糊/拼音输入）查询 A 股基本信息：
- 股票名称、交易所（SH/SZ/BJ）、完整代码（600519.SH）
- 分红信息（每股分红、股息率、除权除息日等）
- 模糊匹配时返回候选列表，供 Agent 确认
"""

from __future__ import annotations

from typing import Any

from ark_agentic.core.tools.base import AgentTool, ToolParameter, read_bool_param, read_string_param_required
from ark_agentic.core.types import AgentToolResult, ToolCall

from ..service import StockSearchService


class SecurityInfoSearchTool(AgentTool):
    """查询股票基本信息（含分红）

    支持输入：
    - 精确 6 位代码（如 "600519"）
    - 股票名称（全称/简称，如 "贵州茅台"、"茅台"）
    - 拼音输入（如 "maotai"、"guizhoumaotai"）
    - 模糊/错误名称（如 "宁德实代" → 宁德时代）
    """

    name = "security_info_search"
    description = (
        "通过 6 位股票代码或股票名称查询 A 股基本信息（名称、交易所、分红等）。"
        "支持模糊匹配，可处理 ASR 识别偏差和用户记忆不准确的情况。"
        "当输入模糊时返回多个候选供确认。"
    )
    thinking_hint = "正在查询股票信息…"
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="6 位股票代码（如 600519）或股票名称/简称/拼音（如 贵州茅台、茅台、maotai）",
            required=True,
        ),
        ToolParameter(
            name="include_dividend",
            type="boolean",
            description="是否包含分红信息，默认为 true",
            required=False,
            default=False,
        ),
    ]

    def __init__(self, service: StockSearchService | None = None) -> None:
        self._service = service or StockSearchService()

    async def execute(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        args = tool_call.arguments or {}
        query = read_string_param_required(args, "query")
        include_dividend = read_bool_param(args, "include_dividend", True)

        try:
            result = self._service.search(
                query, include_dividend=include_dividend, context=context
            )
            return AgentToolResult.json_result(
                tool_call_id=tool_call.id,
                data=result.model_dump(exclude_none=False),
            )
        except Exception as e:
            return AgentToolResult.error_result(
                tool_call_id=tool_call.id,
                error=str(e),
            )
