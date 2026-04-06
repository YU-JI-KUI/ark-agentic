"""RecordCitationsTool — citation 记录工具（框架级，无校验）

职责：仅将 LLM 提交的 citations 写入 session.state["_pending_citations"]。
校验逻辑由 core.validation.create_citation_validation_hook 在 before_complete 阶段执行。
"""

from __future__ import annotations

import logging
from typing import Any

from ..types import AgentToolResult, ToolCall
from .base import AgentTool, ToolParameter

logger = logging.getLogger(__name__)


class RecordCitationsTool(AgentTool):
    """记录本次回答的引用数据到 session state，供 before_complete 校验钩子读取。

    不做任何校验，立即返回成功，LLM 收到 "citations recorded" 后继续输出自然语言回答。
    """

    name = "record_citations"
    description = (
        "在输出最终回答前调用，记录本次回答中所有关键数据的引用来源。"
        "记录成功后直接输出您的自然语言回答，无需再次传入答案文本。"
    )
    parameters = [
        ToolParameter(
            name="citations",
            type="array",
            description=(
                "引用列表，每项包含: value（引用原始值）、"
                "type（NUMBER|TIME|ENTITY）、"
                "source（tool_{工具key} 或 context）"
            ),
            required=True,
            items={
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                    "type": {"type": "string", "enum": ["NUMBER", "TIME", "ENTITY"]},
                    "source": {"type": "string"},
                },
                "required": ["value", "type", "source"],
            },
        ),
    ]

    async def execute(
        self,
        tool_call: ToolCall,
        context: dict[str, Any] | None = None,
    ) -> AgentToolResult:
        args = tool_call.arguments or {}
        raw: list[Any] = args.get("citations", [])

        citations = [
            {"value": str(c["value"]), "type": str(c.get("type", "")).upper(), "source": str(c.get("source", ""))}
            for c in raw
            if isinstance(c, dict) and "value" in c
        ]

        logger.debug("[RECORD_CITATIONS] recorded %d citations", len(citations))

        return AgentToolResult.json_result(
            tool_call_id=tool_call.id,
            data={"ok": True, "message": "citations recorded"},
            metadata={"state_delta": {"_pending_citations": citations}},
        )
