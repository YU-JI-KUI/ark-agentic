"""Tests for format_tool_result_for_history helper."""

from __future__ import annotations

import json

from ark_agentic.core.types import (
    AgentToolResult,
    ToolResultType,
    format_tool_result_for_history,
)


def _make_result(
    tool_call_id: str = "tc_1",
    *,
    content,
    result_type: ToolResultType = ToolResultType.JSON,
    llm_digest: str | None = None,
) -> AgentToolResult:
    return AgentToolResult(
        tool_call_id=tool_call_id,
        result_type=result_type,
        content=content,
        llm_digest=llm_digest,
    )


def test_digest_takes_priority() -> None:
    """When llm_digest is set, it is returned verbatim regardless of content shape."""
    tr = _make_result(
        content={"large": "payload"},
        llm_digest="[卡片:方案 channels=[survival_fund] total=10000]",
    )
    assert (
        format_tool_result_for_history(tr, a2ui_tc_ids=set())
        == "[卡片:方案 channels=[survival_fund] total=10000]"
    )


def test_a2ui_with_list_content_shadows_to_count() -> None:
    """A2UI result type without digest shadows to '[已向用户展示卡片，共N个组件]'."""
    tr = _make_result(
        tool_call_id="tc_a2ui",
        content=[{"type": "Card"}, {"type": "Card"}, {"type": "Footer"}],
        result_type=ToolResultType.A2UI,
    )
    out = format_tool_result_for_history(tr, a2ui_tc_ids={"tc_a2ui"})
    assert out == "[已向用户展示卡片，共3个组件]"


def test_a2ui_with_non_list_content_shadows_with_count_one() -> None:
    """Non-list A2UI content (rare) gets count=1."""
    tr = _make_result(
        tool_call_id="tc_a2ui",
        content={"type": "SingleCard"},
        result_type=ToolResultType.A2UI,
    )
    out = format_tool_result_for_history(tr, a2ui_tc_ids={"tc_a2ui"})
    assert out == "[已向用户展示卡片，共1个组件]"


def test_dict_content_json_dumped() -> None:
    """Dict content without digest/A2UI is JSON-dumped (ensure_ascii=False)."""
    tr = _make_result(content={"name": "保单", "count": 3})
    out = format_tool_result_for_history(tr, a2ui_tc_ids=set())
    assert json.loads(out) == {"name": "保单", "count": 3}
    # ensure non-ASCII characters preserved
    assert "保单" in out


def test_list_content_json_dumped() -> None:
    """List content is JSON-dumped."""
    tr = _make_result(content=[1, 2, 3])
    assert format_tool_result_for_history(tr, a2ui_tc_ids=set()) == "[1, 2, 3]"


def test_string_content_returned_as_is() -> None:
    """String content returned via str()."""
    tr = _make_result(content="hello")
    assert format_tool_result_for_history(tr, a2ui_tc_ids=set()) == "hello"


def test_int_content_stringified() -> None:
    """Non-string scalar gets str()."""
    tr = _make_result(content=42)
    assert format_tool_result_for_history(tr, a2ui_tc_ids=set()) == "42"
