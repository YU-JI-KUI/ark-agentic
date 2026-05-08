"""build_tool_sources_from_session — data_source filtering tests.

Verifies that when a ToolRegistry is passed:
  - tool_call results from data_source=True tools are included
  - tool_call results from data_source=False tools are excluded
  - tool_call results from unknown tools (not in registry) are excluded
  - passing tool_registry=None bypasses filtering (all results included)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ark_agentic.core.runtime.validation import build_tool_sources_from_session
from ark_agentic.core.types import MessageRole


def _make_session_with_calls(
    tool_calls: list[tuple[str, str, str]],
) -> MagicMock:
    """Build a mock session with one USER followed by ASSISTANT+TOOL messages.

    tool_calls: list of (tc_id, tool_name, result_content)
    """
    user_msg = MagicMock()
    user_msg.role = MessageRole.USER
    user_msg.content = "question"
    user_msg.tool_calls = None
    user_msg.tool_results = None

    tcs = []
    for tc_id, name, _ in tool_calls:
        tc = MagicMock()
        tc.id = tc_id
        tc.name = name
        tcs.append(tc)

    assistant_msg = MagicMock()
    assistant_msg.role = MessageRole.ASSISTANT
    assistant_msg.tool_calls = tcs
    assistant_msg.tool_results = None

    trs = []
    for tc_id, _, content in tool_calls:
        tr = MagicMock()
        tr.tool_call_id = tc_id
        tr.content = content
        trs.append(tr)

    tool_msg = MagicMock()
    tool_msg.role = MessageRole.TOOL
    tool_msg.tool_calls = None
    tool_msg.tool_results = trs

    session = MagicMock()
    session.session_id = "test"
    session.messages = [user_msg, assistant_msg, tool_msg]
    return session


def _make_registry(tools: dict[str, bool]) -> MagicMock:
    """tools maps name → data_source flag."""
    registry = MagicMock()

    def _get(name: str) -> MagicMock | None:
        if name not in tools:
            return None
        t = MagicMock()
        t.data_source = tools[name]
        return t

    registry.get.side_effect = _get
    return registry


class TestBuildToolSourcesFiltering:
    def test_data_source_true_tool_is_included(self) -> None:
        session = _make_session_with_calls([("tc1", "policy_query", "5000 元")])
        registry = _make_registry({"policy_query": True})

        result = build_tool_sources_from_session(session, tool_registry=registry)

        assert "tool_policy_query" in result
        assert "5000" in result["tool_policy_query"]

    def test_data_source_false_tool_is_excluded(self) -> None:
        session = _make_session_with_calls([("tc1", "render_a2ui", '{"component": "card"}')])
        registry = _make_registry({"render_a2ui": False})

        result = build_tool_sources_from_session(session, tool_registry=registry)

        assert "tool_render_a2ui" not in result

    def test_unknown_tool_is_excluded_when_registry_passed(self) -> None:
        session = _make_session_with_calls([("tc1", "mystery_tool", "some result")])
        registry = _make_registry({})  # registry has no tools registered

        result = build_tool_sources_from_session(session, tool_registry=registry)

        assert "tool_mystery_tool" not in result

    def test_registry_none_bypasses_filter(self) -> None:
        session = _make_session_with_calls([
            ("tc1", "render_a2ui", '{"x": 1}'),
            ("tc2", "policy_query", "5000 元"),
        ])

        result = build_tool_sources_from_session(session, tool_registry=None)

        assert "tool_render_a2ui" in result
        assert "tool_policy_query" in result

    def test_multiple_tools_filtered_correctly(self) -> None:
        session = _make_session_with_calls([
            ("tc1", "customer_info", "张三"),
            ("tc2", "render_a2ui", '{"component": "card"}'),
            ("tc3", "rule_engine", "费率 0.2%"),
        ])
        registry = _make_registry({
            "customer_info": True,
            "render_a2ui": False,
            "rule_engine": True,
        })

        result = build_tool_sources_from_session(session, tool_registry=registry)

        assert "tool_customer_info" in result
        assert "tool_rule_engine" in result
        assert "tool_render_a2ui" not in result

    def test_empty_session_returns_empty(self) -> None:
        session = MagicMock()
        session.session_id = "s"
        session.messages = []
        registry = _make_registry({"policy_query": True})

        result = build_tool_sources_from_session(session, tool_registry=registry)

        assert result == {}
