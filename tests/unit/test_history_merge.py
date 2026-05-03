"""Tests for external history merge: pair-based dedup, anchor positioning, kill switches."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import json
import tempfile

import pytest

from ark_agentic.core.history_merge import (
    InsertOp,
    _build_external_pairs,
    _build_session_pairs,
    _pairs_match,
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


# ── _build_external_pairs ────────────────────────────────────────────


class TestBuildExternalPairs:
    def test_complete_pairs(self):
        raw = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        pairs = _build_external_pairs(raw)
        assert len(pairs) == 2
        assert pairs[0].user["content"] == "q1"
        assert pairs[0].assistant["content"] == "a1"
        assert pairs[1].user["content"] == "q2"

    def test_trailing_user_dropped(self):
        raw = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "trailing"},
        ]
        pairs = _build_external_pairs(raw)
        assert len(pairs) == 1

    def test_standalone_assistant_dropped(self):
        raw = [
            {"role": "assistant", "content": "orphan"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]
        pairs = _build_external_pairs(raw)
        assert len(pairs) == 1
        assert pairs[0].user["content"] == "q1"

    def test_empty(self):
        assert _build_external_pairs([]) == []

    def test_single_user(self):
        assert _build_external_pairs([{"role": "user", "content": "hi"}]) == []


# ── _build_session_pairs ─────────────────────────────────────────────


class TestBuildSessionPairs:
    def test_filters_tool_messages(self):
        session = [_user("q", 0), _tool_msg(1), _assistant("a", 2)]
        pairs = _build_session_pairs(session)
        assert len(pairs) == 1
        assert pairs[0].user.content == "q"
        assert pairs[0].assistant.content == "a"

    def test_trailing_user_not_paired(self):
        session = [_user("q1", 0), _assistant("a1", 1), _user("q2", 2)]
        pairs = _build_session_pairs(session)
        assert len(pairs) == 1


# ── _pairs_match ─────────────────────────────────────────────────────


class TestPairsMatch:
    def test_exact_match(self):
        from ark_agentic.core.history_merge import _ExternalPair, _SessionPair
        ep = _ExternalPair(
            user={"role": "user", "content": "hello"},
            assistant={"role": "assistant", "content": "world"},
        )
        sp = _SessionPair(user=_user("hello", 0), assistant=_assistant("world", 1))
        assert _pairs_match(ep, sp)

    def test_user_match_assistant_mismatch(self):
        from ark_agentic.core.history_merge import _ExternalPair, _SessionPair
        ep = _ExternalPair(
            user={"role": "user", "content": "你好"},
            assistant={"role": "assistant", "content": "你有什么事？请问需要什么帮助？"},
        )
        sp = _SessionPair(user=_user("你好", 0), assistant=_assistant("你好！很高兴为你服务，有什么需要帮忙的吗？", 1))
        assert not _pairs_match(ep, sp)


# ── merge_external_history (pair-based) ──────────────────────────────


class TestMergeExternalHistory:
    def test_empty_history(self):
        session = [_user("hi", 0), _assistant("hello", 1)]
        assert merge_external_history(session, []) == []
        assert merge_external_history(session, None) == []  # type: ignore[arg-type]

    def test_all_new_no_anchor(self):
        """All external pairs are new → append at end."""
        session = [_user("old question", 0), _assistant("old answer", 1)]
        ext = [
            {"role": "user", "content": "new q1"},
            {"role": "assistant", "content": "new a1"},
        ]
        ops = merge_external_history(session, ext)
        assert len(ops) == 2
        assert ops[0].message.role == MessageRole.USER
        assert ops[1].message.role == MessageRole.ASSISTANT
        for op in ops:
            assert op.anchor_message_id is None
            assert op.message.metadata["source"] == "external"

    def test_all_duplicate(self):
        """Full pair overlap → nothing to insert."""
        session = [_user("hello", 0), _assistant("world", 1)]
        ext = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        assert merge_external_history(session, ext) == []

    def test_same_user_different_assistant_not_duplicate(self):
        """Same user content but different assistant → distinct pairs, both kept."""
        s_user = _user("你好", 0)
        s_asst = _assistant("内部回答：你好！很高兴为你服务。", 1)
        session = [s_user, s_asst]

        ext = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "外部回答：你有什么事"},
        ]
        ops = merge_external_history(session, ext)
        assert len(ops) == 2
        assert ops[0].message.content == "你好"
        assert ops[1].message.content == "外部回答：你有什么事"

    def test_mixed_anchor_before(self):
        """New pair before the first anchor pair → insert_before=True."""
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
        assert ops[0].message.role == MessageRole.USER
        assert ops[1].insert_before is True
        assert ops[1].message.role == MessageRole.ASSISTANT

    def test_mixed_anchor_after(self):
        """New pair after the last anchor pair → insert_before=False."""
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
        """New pair between two anchor pairs → after preceding anchor."""
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

    def test_fuzzy_whitespace(self):
        """Extra whitespace in external content still deduplicates as pair."""
        session = [_user("查询基金收益", 0), _assistant("收益如下", 1)]
        ext = [
            {"role": "user", "content": "  查询基金收益  \n"},
            {"role": "assistant", "content": "收益如下"},
        ]
        assert merge_external_history(session, ext) == []

    def test_fuzzy_truncation(self):
        """Truncated external assistant (~85%+ preserved) still deduplicates."""
        full = "好的，我来为您查询一下这只基金的详细信息和近期表现数据，请您稍等" * 2
        truncated = full[: int(len(full) * 0.88)]
        session = [_user("查基金", 0), _assistant(full, 1)]
        ext = [
            {"role": "user", "content": "查基金"},
            {"role": "assistant", "content": truncated},
        ]
        assert merge_external_history(session, ext) == []

    def test_tool_messages_in_session_ignored_for_pairing(self):
        """Tool messages in session don't affect pair building."""
        s_user = _user("hello", 0)
        s_tool = _tool_msg(1)
        s_asst = _assistant("world", 2)
        session = [s_user, s_tool, s_asst]

        ext = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        assert merge_external_history(session, ext) == []

    def test_source_tag(self):
        """Injected messages carry metadata.source == 'external'."""
        ext = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        ops = merge_external_history([], ext)
        assert len(ops) == 2
        for op in ops:
            assert op.message.metadata["source"] == "external"

    def test_trailing_user_ignored(self):
        """Incomplete trailing user in external history is ignored."""
        session = [_user("old", 0), _assistant("old reply", 1)]
        ext = [
            {"role": "user", "content": "new q"},
            {"role": "assistant", "content": "new a"},
            {"role": "user", "content": "trailing"},
        ]
        ops = merge_external_history(session, ext)
        assert len(ops) == 2
        contents = [op.message.content for op in ops]
        assert "trailing" not in contents

    def test_only_trailing_user_returns_empty(self):
        """External history with only a trailing user → no ops."""
        session = [_user("old", 0), _assistant("reply", 1)]
        ext = [{"role": "user", "content": "just a user"}]
        assert merge_external_history(session, ext) == []

    def test_two_hello_different_responses_both_kept(self):
        """User says '你好' in both systems with different responses → both kept.

        This is the key scenario that pair-based dedup solves: individual
        message matching would incorrectly anchor the user messages together.
        """
        s_user = _user("你好", 0)
        s_asst = _assistant("内部：你好！很高兴为你服务。", 1)
        session = [s_user, s_asst]

        ext = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "外部：你有什么事"},
        ]
        ops = merge_external_history(session, ext)
        assert len(ops) == 2, (
            "Same user content but different assistant → different pairs → inserted"
        )

    def test_invalid_roles_skipped(self):
        """Messages with invalid roles form no pairs → no ops."""
        ext = [
            {"role": "system", "content": "you are helpful"},
            {"role": "tool", "content": "result"},
        ]
        assert merge_external_history([], ext) == []


# ── SessionManager.inject_messages ───────────────────────────────────


class TestInjectMessages:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_sessions_dir: Path) -> None:
        self.sessions_dir = tmp_sessions_dir

    def _make_sm(self) -> tuple[SessionManager, str, str]:
        sm = SessionManager(self.sessions_dir)
        session = sm.create_session_sync(user_id="u1")
        return sm, session.session_id, "u1"

    async def test_inject_appends_at_end(self):
        sm, sid, uid = self._make_sm()
        existing = _user("existing", 0)
        sm.add_message_sync(sid, existing)

        new_msg = _user("new", 10)
        new_msg.metadata["source"] = "external"
        await sm.inject_messages(sid, uid, [InsertOp(message=new_msg, anchor_message_id=None, insert_before=True)])

        messages = sm.get_messages(sid, include_system=False)
        assert len(messages) == 2
        assert messages[-1].content == "new"

    async def test_inject_before_anchor(self):
        sm, sid, uid = self._make_sm()
        anchor = _user("anchor", 5)
        sm.add_message_sync(sid, anchor)

        new_msg = _user("before anchor", 10)
        new_msg.metadata["source"] = "external"
        op = InsertOp(
            message=new_msg,
            anchor_message_id=anchor.timestamp.isoformat(),
            insert_before=True,
        )
        await sm.inject_messages(sid, uid, [op])

        messages = sm.get_messages(sid, include_system=False)
        assert messages[0].content == "before anchor"
        assert messages[1].content == "anchor"

    async def test_inject_after_anchor(self):
        sm, sid, uid = self._make_sm()
        anchor = _user("anchor", 5)
        sm.add_message_sync(sid, anchor)

        new_msg = _assistant("after anchor", 10)
        new_msg.metadata["source"] = "external"
        op = InsertOp(
            message=new_msg,
            anchor_message_id=anchor.timestamp.isoformat(),
            insert_before=False,
        )
        await sm.inject_messages(sid, uid, [op])

        messages = sm.get_messages(sid, include_system=False)
        assert messages[0].content == "anchor"
        assert messages[1].content == "after anchor"

    async def test_inject_persists_immediately(self):
        sm, sid, uid = self._make_sm()
        new_msg = _user("persisted", 10)
        new_msg.metadata["source"] = "external"
        await sm.inject_messages(sid, uid, [InsertOp(message=new_msg, anchor_message_id=None, insert_before=True)])

        # Repository must have the message on disk now (no pending buffer).
        loaded = await sm.repository.load_messages(sid, uid)
        assert any(m.content == "persisted" for m in loaded)

    async def test_inject_preserves_order_multiple_ops(self):
        sm, sid, uid = self._make_sm()
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
        await sm.inject_messages(sid, uid, ops)

        messages = sm.get_messages(sid, include_system=False)
        contents = [m.content for m in messages]
        assert contents == ["a", "anchor", "b"]


# ── persistence: _ensure_trailing_newline ─────────────────────────────


class TestEnsureTrailingNewline:
    def test_adds_newline_when_missing(self, tmp_path: Path):
        from ark_agentic.core.storage.repository.file.session import FileSessionRepository

        f = tmp_path / "test.jsonl"
        f.write_text('{"line":1}', encoding="utf-8")  # no trailing \n
        FileSessionRepository._ensure_trailing_newline(f)
        raw = f.read_bytes()
        assert raw.endswith(b"\n")

    def test_noop_when_newline_exists(self, tmp_path: Path):
        from ark_agentic.core.storage.repository.file.session import FileSessionRepository

        f = tmp_path / "test.jsonl"
        f.write_text('{"line":1}\n', encoding="utf-8")
        size_before = f.stat().st_size
        FileSessionRepository._ensure_trailing_newline(f)
        assert f.stat().st_size == size_before

    def test_noop_on_empty_file(self, tmp_path: Path):
        from ark_agentic.core.storage.repository.file.session import FileSessionRepository

        f = tmp_path / "test.jsonl"
        f.write_text("", encoding="utf-8")
        FileSessionRepository._ensure_trailing_newline(f)
        assert f.stat().st_size == 0

    def test_noop_on_nonexistent_file(self, tmp_path: Path):
        from ark_agentic.core.storage.repository.file.session import FileSessionRepository

        f = tmp_path / "nonexistent.jsonl"
        FileSessionRepository._ensure_trailing_newline(f)  # should not raise

    def test_concatenated_lines_prevented(self, tmp_path: Path):
        """Simulate the bug: file without trailing \\n, then append."""
        from ark_agentic.core.storage.repository.file.session import FileSessionRepository

        f = tmp_path / "test.jsonl"
        f.write_text('{"first":"msg"}', encoding="utf-8")
        FileSessionRepository._ensure_trailing_newline(f)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write('{"second":"msg"}\n')

        lines = [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2
        for line in lines:
            json.loads(line)  # each line must be valid JSON
