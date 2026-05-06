"""Tests for BaseAgent._apply_session_effects (typed tool→session writes)."""

from __future__ import annotations

import pytest

from ark_agentic.core.runtime.base_agent import BaseAgent
from ark_agentic.core.types import AgentToolResult, SessionEntry


def _make_session() -> SessionEntry:
    return SessionEntry.create()


def test_apply_session_effects_activates_skill() -> None:
    session = _make_session()
    tool_results = [
        AgentToolResult.text_result(
            "tc1",
            "digest",
            metadata={
                "session_effects": [
                    {"op": "activate_skill", "skill_ids": ["foo"]},
                ],
            },
        ),
    ]
    BaseAgent._apply_session_effects(session, tool_results)
    assert session.active_skill_ids == ["foo"]


def test_apply_session_effects_does_not_touch_state() -> None:
    """Critical: SSOT lives only on session.active_skill_ids, never in state."""
    session = _make_session()
    tool_results = [
        AgentToolResult.text_result(
            "tc1",
            "digest",
            metadata={
                "session_effects": [
                    {"op": "activate_skill", "skill_ids": ["foo"]},
                ],
            },
        ),
    ]
    BaseAgent._apply_session_effects(session, tool_results)
    assert "_active_skill_id" not in session.state
    assert "_active_skill_ids" not in session.state


def test_apply_session_effects_skips_malformed_silently() -> None:
    """Malformed effect dict → log warning, skip; later valid effects still run."""
    session = _make_session()
    tool_results = [
        AgentToolResult.text_result(
            "tc1",
            "digest",
            metadata={
                "session_effects": [
                    {"op": "bogus_op"},  # invalid op
                    {"op": "activate_skill", "skill_ids": ["good"]},
                ],
            },
        ),
    ]
    # No exception raised; valid effect still applied.
    BaseAgent._apply_session_effects(session, tool_results)
    assert session.active_skill_ids == ["good"]


def test_apply_session_effects_no_effects_field_is_noop() -> None:
    session = _make_session()
    tool_results = [
        AgentToolResult.text_result("tc1", "no metadata", metadata={}),
    ]
    BaseAgent._apply_session_effects(session, tool_results)
    assert session.active_skill_ids == []


def test_apply_session_effects_multiple_results_replace_in_order() -> None:
    """Multiple tool results with activate_skill effects: each call replaces SSOT
    (覆盖式写入). Last tool result wins."""
    session = _make_session()
    tool_results = [
        AgentToolResult.text_result(
            "tc1",
            "first",
            metadata={"session_effects": [
                {"op": "activate_skill", "skill_ids": ["a"]},
            ]},
        ),
        AgentToolResult.text_result(
            "tc2",
            "second",
            metadata={"session_effects": [
                {"op": "activate_skill", "skill_ids": ["b"]},
            ]},
        ),
    ]
    BaseAgent._apply_session_effects(session, tool_results)
    assert session.active_skill_ids == ["b"]
