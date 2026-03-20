"""
Demo A2UI Tool

模拟工具返回 A2UI 组件数据，用于测试完整的 A2UI 流式管道：
  Tool → AgentToolResult(result_type=A2UI, content=组件) → Runner →
  handler.on_ui_component() → StreamEventBus → OutputFormatter → Frontend
"""

from __future__ import annotations

from typing import Any

from .base import AgentTool, ToolParameter
from ..types import AgentToolResult, ToolCall


class DemoA2UITool(AgentTool):
    """演示 A2UI 组件渲染能力的模拟工具。

    返回 result_type=A2UI，content 为 A2UI 卡片组件 dict，由 Runner 转发到流式管线。
    """

    name = "demo_a2ui_card"
    description = "生成一个示例 A2UI 卡片组件，用于演示丰富的前端渲染能力"
    thinking_hint = "正在生成演示卡片…"
    parameters = [
        ToolParameter(
            name="card_title",
            type="string",
            description="卡片标题",
            required=False,
        ),
        ToolParameter(
            name="card_content",
            type="string",
            description="卡片正文内容",
            required=False,
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        args = tool_call.arguments
        title = "保单信息"
        content = "您的保单状态正常，保障至 2027-12-31"

        a2ui_component = {
            "sessionId": (context or {}).get("session_id", "demo"),
            "answerDict": {
                "result": {
                    "answerList": [
                        {
                            "styleId": "0",
                            "card_content_desc": content,
                            "dataList": [
                                {"component": "text", "text": content},
                                {
                                    "component": "button",
                                    "text": "查看详情",
                                    "action": "view_detail",
                                },
                            ],
                        }
                    ]
                }
            },
        }

        return AgentToolResult.a2ui_result(
            tool_call_id=tool_call.id,
            data=a2ui_component,
        )
