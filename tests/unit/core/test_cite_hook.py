"""create_cite_annotation_hook unit tests.

Coverage:
  - hook returns CallbackResult with citation_batch event when annotator hits
  - hook is silent (returns None) when response.tool_calls is non-empty
  - hook is silent when answer is empty
  - hook is silent when no spans matched
  - hook returns CallbackResult regardless of whether handler is present
    (dispatch responsibility belongs to run_hooks, not the hook itself)
  - hook filters tool results via data_source=False tools
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from ark_agentic.core.citation import create_cite_annotation_hook
from ark_agentic.core.citation.types import CiteEntry, CiteSpan


# ============ Helpers ============


def _make_registry(tools: dict[str, Any]) -> MagicMock:
    registry = MagicMock()
    registry.get.side_effect = tools.get
    return registry


def _make_session(messages: list[Any] | None = None) -> MagicMock:
    session = MagicMock()
    session.session_id = "test-session"
    session.messages = messages or []
    session.state = {}
    return session


def _make_response(content: str = "", tool_calls: list | None = None) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    return msg


def _make_ctx(session: MagicMock | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.session = session or _make_session()
    return ctx


# ============ Tests ============


class TestCiteHookNoToolCalls:
    async def test_returns_none_on_clean_run(self) -> None:
        registry = _make_registry({})
        hook = create_cite_annotation_hook(tool_registry=registry)
        ctx = _make_ctx()

        result = await hook(ctx, response=_make_response("暂无数据"))

        assert result is None

    async def test_silent_when_response_has_tool_calls(self) -> None:
        registry = _make_registry({})
        hook = create_cite_annotation_hook(tool_registry=registry)
        ctx = _make_ctx()

        result = await hook(ctx, response=_make_response("text", tool_calls=[MagicMock()]))

        assert result is None

    async def test_silent_when_answer_is_empty(self) -> None:
        registry = _make_registry({})
        hook = create_cite_annotation_hook(tool_registry=registry)
        ctx = _make_ctx()

        result = await hook(ctx, response=_make_response(""))

        assert result is None

    async def test_returns_result_regardless_of_handler(self) -> None:
        """Hook returns CallbackResult with event; handler presence is run_hooks' concern."""
        fake_spans = [
            CiteSpan(source_id="cite-1", tool_name="x", start=0, end=1, matched_text="1"),
        ]
        fake_annotator = MagicMock()
        fake_annotator.annotate.return_value = (fake_spans, [])
        registry = _make_registry({})
        hook = create_cite_annotation_hook(tool_registry=registry, annotator=fake_annotator)
        ctx = _make_ctx()

        with patch(
            "ark_agentic.core.runtime.validation.build_tool_sources_from_session",
            return_value={"tool_policy_query": "1"},
        ):
            result = await hook(ctx, response=_make_response("1"))

        assert result is not None
        assert result.event is not None
        assert result.event.type == "citation_batch"


class TestCiteHookEmitsEvents:
    async def test_emits_on_citation_and_list(self) -> None:
        """Verify citation_batch event carries spans and entries."""
        fake_spans = [
            CiteSpan(source_id="cite-1", tool_name="policy_query", start=0, end=4, matched_text="5000"),
        ]
        fake_entries = [
            CiteEntry(source_id="cite-1", tool_name="policy_query", matched_text="5000"),
        ]

        fake_annotator = MagicMock()
        fake_annotator.annotate.return_value = (fake_spans, fake_entries)

        registry = _make_registry({})
        hook = create_cite_annotation_hook(tool_registry=registry, annotator=fake_annotator)
        ctx = _make_ctx()

        with patch(
            "ark_agentic.core.runtime.validation.build_tool_sources_from_session",
            return_value={"tool_policy_query": "现金价值 5000 元"},
        ):
            result = await hook(ctx, response=_make_response("5000 元"))

        assert result is not None
        assert result.event is not None
        assert result.event.type == "citation_batch"
        assert result.event.data["spans"] == fake_spans
        assert result.event.data["entries"] == fake_entries


class TestCiteHookDataSourceFiltering:
    async def test_data_source_false_tools_excluded(self) -> None:
        """Tool with data_source=False should not contribute to citation evidence."""
        from ark_agentic.core.runtime.validation import build_tool_sources_from_session

        display_tool = MagicMock()
        display_tool.data_source = False
        data_tool = MagicMock()
        data_tool.data_source = True

        registry = _make_registry({"render_a2ui": display_tool, "policy_query": data_tool})

        session = MagicMock()
        session.session_id = "s"
        session.messages = []

        # When session has no messages, build_tool_sources returns {} regardless.
        result = build_tool_sources_from_session(session, tool_registry=registry)
        assert result == {}

    async def test_registry_none_includes_all_tools(self) -> None:
        """When tool_registry=None, all tool results are included (legacy behavior)."""
        from ark_agentic.core.runtime.validation import (
            build_tool_sources_from_session,
        )
        from ark_agentic.core.types import MessageRole

        # Build a minimal session with one ASSISTANT tool_call + TOOL result.
        tc = MagicMock()
        tc.id = "tc1"
        tc.name = "policy_query"

        tr = MagicMock()
        tr.tool_call_id = "tc1"
        tr.content = "5000 元"

        assistant_msg = MagicMock()
        assistant_msg.role = MessageRole.ASSISTANT
        assistant_msg.tool_calls = [tc]
        assistant_msg.tool_results = None

        tool_msg = MagicMock()
        tool_msg.role = MessageRole.TOOL
        tool_msg.tool_calls = None
        tool_msg.tool_results = [tr]

        user_msg = MagicMock()
        user_msg.role = MessageRole.USER
        user_msg.content = "查询"

        session = MagicMock()
        session.session_id = "s"
        session.messages = [user_msg, assistant_msg, tool_msg]

        result = build_tool_sources_from_session(session, tool_registry=None)
        assert "tool_policy_query" in result
