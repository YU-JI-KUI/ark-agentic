"""Contract tests for AgentRunner._build_messages tool-role content."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ark_agentic.core.agent.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.types import (
    AgentMessage,
    AgentToolResult,
    ToolCall,
    ToolResultType,
)


class _NoopChatModel:
    async def ainvoke(self, *_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("not used in build_messages tests")


@pytest.fixture
def tmp_sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir()
    return d


def _make_runner(tmp_sessions_dir: Path) -> AgentRunner:
    return AgentRunner(
        llm=_NoopChatModel(),
        session_manager=SessionManager(tmp_sessions_dir),
        tool_registry=ToolRegistry(),
        config=RunnerConfig(max_turns=3, auto_compact=False),
    )


def _tool_msg_for(messages: list[dict[str, Any]], tc_id: str) -> dict[str, Any]:
    matches = [
        m for m in messages
        if m.get("role") == "tool" and m.get("tool_call_id") == tc_id
    ]
    assert len(matches) == 1, f"expected exactly one tool msg for {tc_id}"
    return matches[0]


async def test_build_messages_uses_llm_digest_for_tool_role(tmp_sessions_dir: Path) -> None:
    runner = _make_runner(tmp_sessions_dir)
    session = runner.session_manager.create_session_sync()

    tc = ToolCall(id="tc_json_1", name="mock_tool", arguments={})
    session.add_message(AgentMessage.user("hi"))
    session.add_message(AgentMessage.assistant(content="", tool_calls=[tc]))
    session.add_message(
        AgentMessage.tool([
            AgentToolResult.json_result("tc_json_1", {"key": "保单值"}),
        ])
    )

    messages = await runner._build_messages(session.session_id, session.state)
    tool_msg = _tool_msg_for(messages, "tc_json_1")
    assert json.loads(tool_msg["content"]) == {"key": "保单值"}


async def test_build_messages_uses_explicit_digest_when_set(tmp_sessions_dir: Path) -> None:
    runner = _make_runner(tmp_sessions_dir)
    session = runner.session_manager.create_session_sync()

    tc = ToolCall(id="tc_dig_1", name="some_business_tool", arguments={})
    session.add_message(AgentMessage.user("q"))
    session.add_message(AgentMessage.assistant(content="", tool_calls=[tc]))
    session.add_message(
        AgentMessage.tool([
            AgentToolResult.json_result(
                "tc_dig_1",
                {"large": "payload", "data": list(range(50))},
                llm_digest="[business] 1 result",
            ),
        ])
    )

    messages = await runner._build_messages(session.session_id, session.state)
    tool_msg = _tool_msg_for(messages, "tc_dig_1")
    assert tool_msg["content"] == "[business] 1 result"


async def test_build_messages_a2ui_uses_factory_default_digest(tmp_sessions_dir: Path) -> None:
    runner = _make_runner(tmp_sessions_dir)
    session = runner.session_manager.create_session_sync()

    tc = ToolCall(id="tc_a2ui_1", name="render_a2ui", arguments={})
    session.add_message(AgentMessage.user("show"))
    session.add_message(AgentMessage.assistant(content="", tool_calls=[tc]))
    session.add_message(
        AgentMessage.tool([
            AgentToolResult.a2ui_result(
                "tc_a2ui_1",
                [{"type": "Card", "secret": 99999}],
            ),
        ])
    )

    messages = await runner._build_messages(session.session_id, session.state)
    tool_msg = _tool_msg_for(messages, "tc_a2ui_1")
    assert tool_msg["content"] == "[已向用户展示卡片]"
    assert "99999" not in tool_msg["content"]


async def test_build_messages_a2ui_error_not_swallowed(tmp_sessions_dir: Path) -> None:
    runner = _make_runner(tmp_sessions_dir)
    session = runner.session_manager.create_session_sync()

    tc = ToolCall(id="tc_a2ui_err", name="render_a2ui", arguments={})
    session.add_message(AgentMessage.user("show plan"))
    session.add_message(AgentMessage.assistant(content="", tool_calls=[tc]))
    session.add_message(
        AgentMessage.tool([
            AgentToolResult.error_result(
                "tc_a2ui_err",
                "Template not found: withdraw_summary.json",
            ),
        ])
    )

    messages = await runner._build_messages(session.session_id, session.state)
    tool_msg = _tool_msg_for(messages, "tc_a2ui_err")
    assert "Template not found" in tool_msg["content"]
    assert "withdraw_summary.json" in tool_msg["content"]
    assert "[已向用户展示卡片" not in tool_msg["content"]


async def test_build_messages_a2ui_tool_call_args_preserved(tmp_sessions_dir: Path) -> None:
    runner = _make_runner(tmp_sessions_dir)
    session = runner.session_manager.create_session_sync()

    blocks_payload = [{"type": "WithdrawPlanCard", "data": {"target": 10000}}]
    tc = ToolCall(
        id="tc_args",
        name="render_a2ui",
        arguments={"blocks": json.dumps(blocks_payload)},
    )
    session.add_message(AgentMessage.user("取10000"))
    session.add_message(AgentMessage.assistant(content="", tool_calls=[tc]))
    session.add_message(
        AgentMessage.tool([
            AgentToolResult.a2ui_result("tc_args", {"event": "beginRendering"}),
        ])
    )

    messages = await runner._build_messages(session.session_id, session.state)
    assistant_msgs = [
        m for m in messages
        if m["role"] == "assistant" and m.get("tool_calls")
    ]
    assert len(assistant_msgs) == 1
    args = json.loads(assistant_msgs[0]["tool_calls"][0]["function"]["arguments"])
    assert args["blocks"] == json.dumps(blocks_payload)
