from __future__ import annotations

from pathlib import Path

import pytest
from unittest.mock import MagicMock

from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.tools.base import AgentTool
from ark_agentic.core.tools.executor import ToolExecutor
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import AgentMessage, AgentToolResult, ToolCall, ToolResultType


class _NoopTool(AgentTool):
    name = "noop"
    description = "noop"
    parameters = []

    async def execute(self, tool_call: ToolCall, context: dict | None = None) -> AgentToolResult:
        return AgentToolResult.json_result(tool_call.id, {"ok": True})


def _make_runner(tmp_path: Path) -> AgentRunner:
    registry = ToolRegistry()
    registry.register(_NoopTool())

    class _LLM:
        def bind_tools(self, tools, **kwargs):
            return self

        def model_copy(self, update=None):
            return self

    return AgentRunner(
        llm=_LLM(),  # type: ignore[arg-type]
        session_manager=SessionManager(tmp_path),
        tool_registry=registry,
        config=RunnerConfig(auto_compact=False),
    )


def test_build_messages_prefers_guardrails_llm_visible_content(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    session = runner.session_manager.create_session_sync(user_id="u1")
    session.add_message(AgentMessage.user("hi"))
    session.add_message(
        AgentMessage.tool([
            AgentToolResult.json_result(
                "tc1",
                {"card_no": "6217000012345678"},
                metadata={"guardrails": {"llm_visible_content": {"card_no": "6217********5678"}}},
            )
        ])
    )

    messages = runner._build_messages(session.session_id, session.state)

    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert "6217********5678" in tool_msgs[0]["content"]
    assert "6217000012345678" not in tool_msgs[0]["content"]


@pytest.mark.asyncio
async def test_executor_prefers_guardrails_ui_visible_content() -> None:
    reg = ToolRegistry()

    class _VisibleTool(AgentTool):
        name = "visible"
        description = "visible"
        parameters = []

        async def execute(self, tool_call: ToolCall, context: dict | None = None) -> AgentToolResult:
            return AgentToolResult.json_result(
                tool_call.id,
                {"card_no": "6217000012345678"},
                metadata={"guardrails": {"ui_visible_content": {"card_no": "6217********5678"}}},
            )

    reg.register(_VisibleTool())
    handler = MagicMock()
    executor = ToolExecutor(reg)

    await executor.execute([ToolCall.create("visible", {})], {}, handler=handler)

    args = handler.on_tool_call_result.call_args[0]
    assert args[2] == {"card_no": "6217********5678"}

