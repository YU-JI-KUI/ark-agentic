"""Tests for external history merge: dedup, anchor positioning, kill switches."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ark_agentic.core.history_merge import (
    InsertOp,
    is_duplicate,
    merge_external_history,
    normalize_content,
)
from ark_agentic.core.session import SessionManager
from ark_agentic.core.types import AgentMessage, MessageRole


# ── helpers ──────────────────────────────────────────────────────────


def _user(content: str, ts_offset: int = 0, **meta: object) -> AgentMessage:
    return AgentMessage(
        role=MessageRole.USER,
        content=content,
        timestamp=datetime(2026, 3, 14, 12, 0, ts_offset),
        metadata=dict(meta),
    )


def _assistant(content: str, ts_offset: int = 0, **meta: object) -> AgentMessage:
    return AgentMessage(
        role=MessageRole.ASSISTANT,
        content=content,
        timestamp=datetime(2026, 3, 14, 12, 0, ts_offset),
        metadata=dict(meta),
    )


def _tool_msg(ts_offset: int = 0) -> AgentMessage:
    """Stub tool message to verify it doesn't interfere with dedup window."""
    return AgentMessage(
        role=MessageRole.TOOL,
        content="tool result placeholder",
        timestamp=datetime(2026, 3, 14, 12, 0, ts_offset),
    )


# ── normalize_content ────────────────────────────────────────────────


class TestNormalizeContent:
    def test_strip_and_collapse(self):
        assert normalize_content("  hello   world\n\t") == "hello world"

    def test_lowercase(self):
        assert normalize_content("Hello WORLD") == "hello world"

    def test_empty(self):
        assert normalize_content("") == ""


# ── is_duplicate ─────────────────────────────────────────────────────


class TestIsDuplicate:
    def test_exact_match(self):
        assert is_duplicate("hello", "hello")

    def test_whitespace_difference(self):
        assert is_duplicate("hello  world\n", "hello world")

    def test_completely_different(self):
        assert not is_duplicate("hello world", "goodbye moon")

    def test_fuzzy_truncation(self):
        long_text = "这是一段比较长的对话内容，用来测试截断场景下的模糊匹配" * 3
        truncated = long_text[:60]
        assert is_duplicate(long_text, truncated)

    def test_short_text_with_punctuation(self):
        assert is_duplicate("好的", "好的。")

    def test_short_text_different(self):
        assert not is_duplicate("好的", "不好")

    def test_short_text_ok_vs_ok_dot(self):
        assert is_duplicate("OK", "OK.")

    def test_empty_strings(self):
        assert is_duplicate("", "")

    def test_one_empty(self):
        assert not is_duplicate("hello", "")


# ── merge_external_history ───────────────────────────────────────────


class TestMergeExternalHistory:
    def test_empty_history(self):
        session = [_user("hi", 0), _assistant("hello", 1)]
        assert merge_external_history(session, []) == []
        assert merge_external_history(session, None) == []  # type: ignore[arg-type]

    def test_all_new_no_anchor(self):
        """All external messages are new → append at end."""
        session = [_user("old question", 0), _assistant("old answer", 1)]
        ext = [
            {"role": "user", "content": "new q1"},
            {"role": "assistant", "content": "new a1"},
        ]
        ops = merge_external_history(session, ext)
        assert len(ops) == 2
        for op in ops:
            assert op.anchor_message_id is None
            assert op.message.metadata["source"] == "external"

    def test_all_duplicate(self):
        """Full overlap → nothing to insert."""
        session = [_user("hello", 0), _assistant("world", 1)]
        ext = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        ops = merge_external_history(session, ext)
        assert ops == []

    def test_mixed_anchor_before(self):
        """New message before the first anchor → insert_before=True."""
        s_user = _user("查下基金", 2)
        s_asst = _assistant("好的，为您查询", 3)
        session = [s_user, s_asst]

        ext = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好，请问有什么需要"},
            {"role": "user", "content": "查下基金"},
            {"role": "assistant", "content": "好的，为您查询"},
        ]
        ops = merge_external_history(session, ext)
        assert len(ops) == 2
        assert ops[0].insert_before is True
        assert ops[0].anchor_message_id == s_user.timestamp.isoformat()
        assert ops[1].insert_before is True

    def test_mixed_anchor_after(self):
        """New messages after the last anchor → insert_before=False."""
        s_user = _user("你好", 0)
        s_asst = _assistant("您好", 1)
        session = [s_user, s_asst]

        ext = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好"},
            {"role": "user", "content": "查下基金"},
            {"role": "assistant", "content": "好的"},
        ]
        ops = merge_external_history(session, ext)
        assert len(ops) == 2
        assert ops[0].insert_before is False
        assert ops[0].anchor_message_id == s_asst.timestamp.isoformat()

    def test_mixed_between_anchors(self):
        """New message between two anchors → after preceding anchor."""
        s1u = _user("问题一", 0)
        s1a = _assistant("回答一", 1)
        s2u = _user("问题三", 4)
        s2a = _assistant("回答三", 5)
        session = [s1u, s1a, s2u, s2a]

        ext = [
            {"role": "user", "content": "问题一"},
            {"role": "assistant", "content": "回答一"},
            {"role": "user", "content": "问题二"},
            {"role": "assistant", "content": "回答二"},
            {"role": "user", "content": "问题三"},
            {"role": "assistant", "content": "回答三"},
        ]
        ops = merge_external_history(session, ext)
        assert len(ops) == 2
        assert ops[0].anchor_message_id == s1a.timestamp.isoformat()
        assert ops[0].insert_before is False
        assert ops[1].anchor_message_id == s1a.timestamp.isoformat()
        assert ops[1].insert_before is False

    def test_fuzzy_whitespace(self):
        """Extra whitespace in external content still deduplicates."""
        session = [_user("查询基金收益", 0), _assistant("收益如下", 1)]
        ext = [
            {"role": "user", "content": "  查询基金收益  \n"},
            {"role": "assistant", "content": "收益如下"},
        ]
        ops = merge_external_history(session, ext)
        assert ops == []

    def test_fuzzy_truncation(self):
        """Truncated external content (~85%+ preserved) still deduplicates."""
        full = "好的，我来为您查询一下这只基金的详细信息和近期表现数据，请您稍等" * 2
        truncated = full[: int(len(full) * 0.88)]
        session = [_user("查基金", 0), _assistant(full, 1)]
        ext = [
            {"role": "user", "content": "查基金"},
            {"role": "assistant", "content": truncated},
        ]
        ops = merge_external_history(session, ext)
        assert ops == []

    def test_tool_messages_in_session_ignored_for_dedup(self):
        """Tool messages in session don't enter the dedup window."""
        s_user = _user("hello", 0)
        s_tool = _tool_msg(1)
        s_asst = _assistant("world", 2)
        session = [s_user, s_tool, s_asst]

        ext = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        ops = merge_external_history(session, ext)
        assert ops == []

    def test_source_tag(self):
        """Injected messages carry metadata.source == 'external'."""
        ops = merge_external_history([], [{"role": "user", "content": "hi"}])
        assert len(ops) == 1
        assert ops[0].message.metadata["source"] == "external"
        assert ops[0].message.role == MessageRole.USER
        assert ops[0].message.content == "hi"

    # ── structural pair check ────────────────────────────────────────

    def test_divergent_assistant_skipped(self):
        """Same user message handled by both systems → external assistant skipped.

        Scenario: user says "你好" once.
        Internal handled it: user:"你好" → assistant:"你好！很高兴为你服务。"
        External also saw it: user:"你好" → assistant:"你有什么事"

        The external assistant response is a divergent reply to an already-
        completed internal turn. It must be skipped to avoid two consecutive
        assistant messages.
        """
        s_user = _user("你好", 0)
        s_asst = _assistant("你好！很高兴为你服务。", 1)
        session = [s_user, s_asst]

        ext = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你有什么事"},
        ]
        ops = merge_external_history(session, ext)
        assert ops == [], (
            "External assistant after a matched user anchor with existing internal "
            "assistant must be skipped"
        )

    def test_divergent_assistant_skipped_mid_conversation(self):
        """Divergent response skip works even when the matched turn is not the first."""
        s_u1 = _user("问题一", 0)
        s_a1 = _assistant("内部回答一", 1)
        s_u2 = _user("你好", 2)
        s_a2 = _assistant("你好！很高兴为你服务。", 3)
        session = [s_u1, s_a1, s_u2, s_a2]

        ext = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你有什么事"},
        ]
        ops = merge_external_history(session, ext)
        assert ops == []

    def test_external_assistant_injected_when_no_internal_followup(self):
        """External assistant IS injected when matched user has no internal assistant yet.

        Scenario: user said "你好" and it appears in external history with an
        external assistant response, but the internal session only has the user
        message (assistant reply not yet added internally).
        """
        s_user = _user("你好", 0)
        session = [s_user]  # no assistant yet

        ext = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你有什么事"},
        ]
        ops = merge_external_history(session, ext)
        assert len(ops) == 1
        assert ops[0].message.role == MessageRole.ASSISTANT
        assert ops[0].message.content == "你有什么事"

    def test_two_independent_hello_turns(self):
        """User says '你好' twice — each turn handled by a different system.

        Internal: user:"你好"₁ → assistant:"I1"
        External: [user:"你好"₁ → assistant:"E1"]  (only external saw turn 1)

        The external user matches the internal user (same content, used_window
        prevents double-matching). External assistant E1 is checked: internal
        already has assistant I1 after that anchor → E1 skipped.
        Result: no ops — internal history is authoritative for that turn.
        """
        s_u1 = _user("你好", 0)
        s_a1 = _assistant("I1", 1)
        session = [s_u1, s_a1]

        ext = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "E1"},
        ]
        ops = merge_external_history(session, ext)
        assert ops == []

    def test_external_new_user_after_divergent_skip(self):
        """After skipping a divergent assistant, subsequent new user is still injected."""
        s_user = _user("你好", 0)
        s_asst = _assistant("内部回答", 1)
        session = [s_user, s_asst]

        ext = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "外部回答"},  # divergent → skipped
            {"role": "user", "content": "后续新问题"},     # genuinely new → injected
        ]
        ops = merge_external_history(session, ext)
        assert len(ops) == 1
        assert ops[0].message.role == MessageRole.USER
        assert ops[0].message.content == "后续新问题"


# ── SessionManager.inject_messages ───────────────────────────────────


class TestInjectMessages:
    def _make_sm(self) -> tuple[SessionManager, str]:
        sm = SessionManager(enable_persistence=False)
        session = sm.create_session_sync()
        return sm, session.session_id

    def test_inject_appends_at_end(self):
        sm, sid = self._make_sm()
        existing = _user("existing", 0)
        sm.add_message_sync(sid, existing)

        new_msg = _user("new", 10)
        new_msg.metadata["source"] = "external"
        sm.inject_messages(sid, [InsertOp(message=new_msg, anchor_message_id=None, insert_before=True)])

        messages = sm.get_messages(sid, include_system=False)
        assert len(messages) == 2
        assert messages[-1].content == "new"

    def test_inject_before_anchor(self):
        sm, sid = self._make_sm()
        anchor = _user("anchor", 5)
        sm.add_message_sync(sid, anchor)

        new_msg = _user("before anchor", 10)
        new_msg.metadata["source"] = "external"
        op = InsertOp(
            message=new_msg,
            anchor_message_id=anchor.timestamp.isoformat(),
            insert_before=True,
        )
        sm.inject_messages(sid, [op])

        messages = sm.get_messages(sid, include_system=False)
        assert messages[0].content == "before anchor"
        assert messages[1].content == "anchor"

    def test_inject_after_anchor(self):
        sm, sid = self._make_sm()
        anchor = _user("anchor", 5)
        sm.add_message_sync(sid, anchor)

        new_msg = _assistant("after anchor", 10)
        new_msg.metadata["source"] = "external"
        op = InsertOp(
            message=new_msg,
            anchor_message_id=anchor.timestamp.isoformat(),
            insert_before=False,
        )
        sm.inject_messages(sid, [op])

        messages = sm.get_messages(sid, include_system=False)
        assert messages[0].content == "anchor"
        assert messages[1].content == "after anchor"

    def test_inject_marks_pending(self):
        sm, sid = self._make_sm()
        new_msg = _user("pending", 10)
        new_msg.metadata["source"] = "external"
        sm.inject_messages(sid, [InsertOp(message=new_msg, anchor_message_id=None, insert_before=True)])

        session = sm.get_session_required(sid)
        assert hasattr(session, "_pending_messages")
        assert any(m.content == "pending" for m in session._pending_messages)

    def test_inject_preserves_order_multiple_ops(self):
        sm, sid = self._make_sm()
        anchor = _user("anchor", 5)
        sm.add_message_sync(sid, anchor)

        msg_a = _user("a", 10)
        msg_b = _assistant("b", 11)
        for m in (msg_a, msg_b):
            m.metadata["source"] = "external"

        ops = [
            InsertOp(message=msg_a, anchor_message_id=anchor.timestamp.isoformat(), insert_before=True),
            InsertOp(message=msg_b, anchor_message_id=anchor.timestamp.isoformat(), insert_before=False),
        ]
        sm.inject_messages(sid, ops)

        messages = sm.get_messages(sid, include_system=False)
        contents = [m.content for m in messages]
        assert contents == ["a", "anchor", "b"]
