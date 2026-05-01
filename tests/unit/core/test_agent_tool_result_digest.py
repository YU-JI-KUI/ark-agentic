"""Tests for AgentToolResult.llm_digest property + fallback chain."""

from __future__ import annotations

import json

from ark_agentic.core.persistence import (
    deserialize_tool_result,
    serialize_tool_result,
)
from ark_agentic.core.types import AgentToolResult, ToolResultType


# ============ property fallback ============


def test_explicit_digest_is_returned() -> None:
    tr = AgentToolResult(
        tool_call_id="tc",
        result_type=ToolResultType.JSON,
        content={"large": "payload"},
    )
    tr.llm_digest = "[explicit summary]"
    assert tr.llm_digest == "[explicit summary]"


def test_dict_content_falls_back_to_json_dump() -> None:
    tr = AgentToolResult(
        tool_call_id="tc",
        result_type=ToolResultType.JSON,
        content={"name": "保单", "count": 3},
    )
    out = tr.llm_digest
    assert isinstance(out, str)
    # ensure_ascii=False keeps Chinese chars literal
    assert "保单" in out
    assert json.loads(out) == {"name": "保单", "count": 3}


def test_list_content_falls_back_to_json_dump() -> None:
    tr = AgentToolResult(
        tool_call_id="tc",
        result_type=ToolResultType.JSON,
        content=[1, 2, 3],
    )
    assert tr.llm_digest == "[1, 2, 3]"


def test_string_content_falls_back_to_str() -> None:
    tr = AgentToolResult(
        tool_call_id="tc",
        result_type=ToolResultType.TEXT,
        content="hello",
    )
    assert tr.llm_digest == "hello"


def test_int_content_falls_back_to_str() -> None:
    tr = AgentToolResult(
        tool_call_id="tc",
        result_type=ToolResultType.JSON,
        content=42,
    )
    assert tr.llm_digest == "42"


def test_error_message_falls_back_to_str() -> None:
    tr = AgentToolResult.error_result("tc", "boom: something failed")
    assert tr.llm_digest == "boom: something failed"


# ============ setter ============


def test_setter_writes_through() -> None:
    tr = AgentToolResult(
        tool_call_id="tc",
        result_type=ToolResultType.JSON,
        content={"x": 1},
    )
    # before set, falls back to JSON dump
    assert json.loads(tr.llm_digest) == {"x": 1}
    tr.llm_digest = "custom digest"
    assert tr.llm_digest == "custom digest"


def test_setter_can_clear_back_to_fallback() -> None:
    tr = AgentToolResult(
        tool_call_id="tc",
        result_type=ToolResultType.JSON,
        content={"x": 1},
        llm_digest="something",
    )
    assert tr.llm_digest == "something"
    tr.llm_digest = None
    # falls back to JSON dump
    assert json.loads(tr.llm_digest) == {"x": 1}


# ============ factory methods accept llm_digest kwarg ============


def test_json_result_factory_accepts_digest_kwarg() -> None:
    tr = AgentToolResult.json_result("tc", {"a": 1}, llm_digest="d")
    assert tr.llm_digest == "d"


def test_text_result_factory_accepts_digest_kwarg() -> None:
    tr = AgentToolResult.text_result("tc", "raw text", llm_digest="d")
    assert tr.llm_digest == "d"


def test_image_result_factory_accepts_digest_kwarg() -> None:
    tr = AgentToolResult.image_result("tc", "<base64>", llm_digest="d")
    assert tr.llm_digest == "d"


def test_factory_without_digest_falls_back() -> None:
    tr = AgentToolResult.json_result("tc", {"x": 1})
    assert json.loads(tr.llm_digest) == {"x": 1}


# ============ persistence: disk key remains 'llm_digest' ============


def test_serialize_writes_disk_key_llm_digest() -> None:
    tr = AgentToolResult(
        tool_call_id="tc",
        result_type=ToolResultType.JSON,
        content={"x": 1},
        llm_digest="explicit",
    )
    data = serialize_tool_result(tr)
    assert "llm_digest" in data
    assert data["llm_digest"] == "explicit"
    assert "_llm_digest" not in data


def test_serialize_omits_digest_when_not_explicitly_set() -> None:
    tr = AgentToolResult(
        tool_call_id="tc",
        result_type=ToolResultType.JSON,
        content={"x": 1},
    )
    data = serialize_tool_result(tr)
    assert "llm_digest" not in data


def test_deserialize_reads_disk_key_llm_digest() -> None:
    data = {
        "tool_call_id": "tc",
        "result_type": "json",
        "content": '{"x": 1}',
        "is_error": False,
        "llm_digest": "from-disk",
    }
    tr = deserialize_tool_result(data)
    assert tr.llm_digest == "from-disk"


def test_roundtrip_explicit_digest() -> None:
    original = AgentToolResult.json_result(
        "tc", {"x": 1}, llm_digest="round-trip",
    )
    data = serialize_tool_result(original)
    loaded = deserialize_tool_result(data)
    assert loaded.llm_digest == "round-trip"


def test_roundtrip_no_explicit_digest_uses_fallback_after_load() -> None:
    original = AgentToolResult.json_result("tc", {"x": 1})
    data = serialize_tool_result(original)
    assert "llm_digest" not in data
    loaded = deserialize_tool_result(data)
    assert isinstance(loaded.content, dict)
    assert json.loads(loaded.llm_digest) == {"x": 1}


# ============ a2ui_result factory default digest ============


def test_a2ui_result_default_digest_when_not_provided() -> None:
    tr = AgentToolResult.a2ui_result(
        "tc_a2ui",
        [{"type": "Card"}, {"type": "Card"}],
    )
    assert tr.llm_digest == "[已向用户展示卡片]"


def test_a2ui_result_default_digest_for_dict_content() -> None:
    tr = AgentToolResult.a2ui_result(
        "tc_a2ui",
        {"type": "SingleCard"},
    )
    assert tr.llm_digest == "[已向用户展示卡片]"


def test_a2ui_result_explicit_digest_overrides_default() -> None:
    tr = AgentToolResult.a2ui_result(
        "tc_a2ui",
        [{"type": "Card"}],
        llm_digest="[plan_card] survival_fund=10000",
    )
    assert tr.llm_digest == "[plan_card] survival_fund=10000"


def test_a2ui_result_attach_enrichment_can_override_default() -> None:
    from ark_agentic.core.a2ui.blocks import A2UIOutput
    from ark_agentic.core.tools.render_a2ui import _attach_enrichment

    tr = AgentToolResult.a2ui_result("tc_a2ui", [{"type": "Card"}])
    assert tr.llm_digest == "[已向用户展示卡片]"

    output = A2UIOutput(components=[{"type": "Card"}], llm_digest="[business digest]")
    _attach_enrichment(tr, output)
    assert tr.llm_digest == "[business digest]"


def test_a2ui_result_attach_enrichment_keeps_default_if_output_digest_empty() -> None:
    """Empty A2UIOutput.llm_digest must not clobber the factory default."""
    from ark_agentic.core.a2ui.blocks import A2UIOutput
    from ark_agentic.core.tools.render_a2ui import _attach_enrichment

    tr = AgentToolResult.a2ui_result("tc_a2ui", [{"type": "Card"}])
    output = A2UIOutput(components=[{"type": "Card"}], llm_digest="")
    _attach_enrichment(tr, output)
    assert tr.llm_digest == "[已向用户展示卡片]"
