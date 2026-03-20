"""
演示 Session State 用法的两个工具

- SetStateDemoTool：将键值对写入 session.state（通过 result.metadata.state_delta）
- GetStateDemoTool：从 session.state（即 execute 的 context）读取键对应的值
"""

from __future__ import annotations

from typing import Any

from .base import AgentTool, ToolParameter, read_string_param
from ..types import AgentToolResult, ToolCall


class SetStateDemoTool(AgentTool):
    """演示：向 session state 写入键值对。

    通过返回 metadata.state_delta，Runner 会在本轮工具执行后将 delta 合并进 session.state，
    后续轮次或其他工具可通过 context 读到。
    """

    name = "demo_set_state"
    thinking_hint = "正在更新演示状态…"
    description = (
        "Write a key-value pair into the session state. "
        "Use this to store data (e.g. user preference, selected option) for later use in the same session. "
        "The value is merged into session state after this tool runs; other tools or later turns can read it."
    )
    parameters = [
        ToolParameter(
            name="key",
            type="string",
            description="State key (e.g. selected_plan, user_preference). Prefer snake_case.",
            required=True,
        ),
        ToolParameter(
            name="value",
            type="string",
            description="Value to store (string). For complex data use JSON string.",
            required=True,
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        args = tool_call.arguments or {}
        key = read_string_param(args, "key", "")
        value = read_string_param(args, "value", "")

        if not key or not key.strip():
            return AgentToolResult.error_result(
                tool_call.id, "key is required and must be non-empty."
            )

        key = key.strip()
        state_delta = {key: value}

        return AgentToolResult.json_result(
            tool_call.id,
            {"ok": True, "key": key, "message": f"State key '{key}' has been set."},
            metadata={"state_delta": state_delta},
        )


class GetStateDemoTool(AgentTool):
    """演示：从 session state 读取键对应的值。

    context 由 Runner 注入，包含 session.state；读取 context[key] 即可。
    """

    name = "demo_get_state"
    thinking_hint = "正在读取演示状态…"
    description = (
        "Read a value from the session state by key. "
        "Use this to retrieve data previously stored with demo_set_state (e.g. selected_plan, user_preference). "
        "Returns the value if the key exists, otherwise a clear message."
    )
    parameters = [
        ToolParameter(
            name="key",
            type="string",
            description="State key to read (e.g. selected_plan, user_preference).",
            required=True,
        ),
    ]

    async def execute(
        self, tool_call: ToolCall, context: dict[str, Any] | None = None
    ) -> AgentToolResult:
        args = tool_call.arguments or {}
        key = read_string_param(args, "key", "")

        if not key or not key.strip():
            return AgentToolResult.error_result(
                tool_call.id, "key is required and must be non-empty."
            )

        key = key.strip()
        ctx = context or {}

        if key not in ctx:
            return AgentToolResult.json_result(
                tool_call.id,
                {"found": False, "key": key, "message": f"No state found for key '{key}'."},
            )

        return AgentToolResult.json_result(
            tool_call.id,
            {"found": True, "key": key, "value": ctx[key]},
        )
