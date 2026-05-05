"""External history merge: pair-based dedup + anchor-based positioning

Merges externally-provided chat history into the session's unified
message timeline. Pure functions — no side effects, no session mutation.

Dedup operates on (user, assistant) conversation pairs rather than
individual messages. A pair matches only when BOTH user AND assistant
content are duplicates. Incomplete trailing pairs (user without
assistant) are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from ..types import AgentMessage, MessageRole


@dataclass
class InsertOp:
    """Describes where to insert an external message relative to a session anchor."""

    message: AgentMessage
    anchor_message_id: str | None  # timestamp isoformat of anchor; None → append
    insert_before: bool


# ── pair data structures ──────────────────────────────────────────────


@dataclass
class _ExternalPair:
    user: dict
    assistant: dict


@dataclass
class _SessionPair:
    user: AgentMessage
    assistant: AgentMessage


# ── text comparison primitives ────────────────────────────────────────


def normalize_content(text: str) -> str:
    """Strip, collapse whitespace, lowercase for fuzzy comparison."""
    return re.sub(r"\s+", " ", text.strip()).lower()


def is_duplicate(
    a: str,
    b: str,
    *,
    short_threshold: float = 0.75,
    long_threshold: float = 0.85,
    short_len: int = 20,
) -> bool:
    """Adaptive-threshold fuzzy duplicate check via SequenceMatcher."""
    na = normalize_content(a)
    nb = normalize_content(b)
    if not na and not nb:
        return True
    if not na or not nb:
        return False
    threshold = (
        short_threshold
        if len(na) < short_len or len(nb) < short_len
        else long_threshold
    )
    return SequenceMatcher(None, na, nb).ratio() >= threshold


# ── pair building ─────────────────────────────────────────────────────


def _build_external_pairs(raw_history: list[dict[str, Any]]) -> list[_ExternalPair]:
    """Group consecutive (user, assistant) messages into complete pairs.

    Incomplete trailing messages (user without assistant, or standalone
    assistant) are silently dropped.
    """
    pairs: list[_ExternalPair] = []
    i = 0
    while i < len(raw_history) - 1:
        cur = raw_history[i]
        nxt = raw_history[i + 1]
        if (
            cur.get("role") == MessageRole.USER.value
            and nxt.get("role") == MessageRole.ASSISTANT.value
        ):
            pairs.append(_ExternalPair(user=cur, assistant=nxt))
            i += 2
        else:
            i += 1
    return pairs


def _build_session_pairs(
    session_messages: list[AgentMessage],
) -> list[_SessionPair]:
    """Group consecutive user/assistant AgentMessages into complete pairs.

    Filters to user/assistant roles first, then pairs adjacently.
    """
    ua = [
        m for m in session_messages
        if m.role in (MessageRole.USER, MessageRole.ASSISTANT)
    ]
    pairs: list[_SessionPair] = []
    i = 0
    while i < len(ua) - 1:
        if (
            ua[i].role == MessageRole.USER
            and ua[i + 1].role == MessageRole.ASSISTANT
        ):
            pairs.append(_SessionPair(user=ua[i], assistant=ua[i + 1]))
            i += 2
        else:
            i += 1
    return pairs


# ── pair matching ─────────────────────────────────────────────────────


def _pairs_match(
    ext: _ExternalPair,
    sess: _SessionPair,
    *,
    short_threshold: float = 0.75,
    long_threshold: float = 0.85,
) -> bool:
    """A pair matches when both user AND assistant content are duplicates."""
    kwargs = dict(short_threshold=short_threshold, long_threshold=long_threshold)
    if not is_duplicate(
        ext.user.get("content", ""),
        sess.user.content or "",
        **kwargs,
    ):
        return False
    return is_duplicate(
        ext.assistant.get("content", ""),
        sess.assistant.content or "",
        **kwargs,
    )


# ── main entry point ─────────────────────────────────────────────────


def merge_external_history(
    session_messages: list[AgentMessage],
    raw_history: list[dict[str, Any]],
    *,
    short_threshold: float = 0.75,
    long_threshold: float = 0.85,
) -> list[InsertOp]:
    """Compute InsertOps to merge *raw_history* into *session_messages*.

    Dedup is pair-based: external history is grouped into (user, assistant)
    pairs. A pair is considered duplicate only when both user AND assistant
    content match a session pair. Incomplete trailing messages are ignored.

    Returns a list of :class:`InsertOp` — the caller (SessionManager) is
    responsible for resolving ``anchor_message_id`` to an actual index and
    performing the insertion.
    """
    if not raw_history:
        return []

    ext_pairs = _build_external_pairs(raw_history)
    if not ext_pairs:
        return []

    sess_pairs = _build_session_pairs(session_messages)
    window = sess_pairs[-len(ext_pairs):] if sess_pairs else []

    # Match external pairs against session window
    anchor_map: dict[int, _SessionPair] = {}
    used_window: set[int] = set()

    match_kwargs = dict(
        short_threshold=short_threshold,
        long_threshold=long_threshold,
    )

    for ei, ep in enumerate(ext_pairs):
        for wi, wp in enumerate(window):
            if wi in used_window:
                continue
            if _pairs_match(ep, wp, **match_kwargs):
                anchor_map[ei] = wp
                used_window.add(wi)
                break

    if len(anchor_map) == len(ext_pairs):
        return []

    # Emit InsertOps for non-matched pairs
    ops: list[InsertOp] = []
    last_anchor: _SessionPair | None = None

    first_anchor: _SessionPair | None = None
    for ei in range(len(ext_pairs)):
        if ei in anchor_map:
            first_anchor = anchor_map[ei]
            break

    for ei, ep in enumerate(ext_pairs):
        if ei in anchor_map:
            last_anchor = anchor_map[ei]
            continue

        user_msg = AgentMessage(
            role=MessageRole.USER,
            content=ep.user.get("content", ""),
            metadata={"source": "external"},
        )
        asst_msg = AgentMessage(
            role=MessageRole.ASSISTANT,
            content=ep.assistant.get("content", ""),
            metadata={"source": "external"},
        )

        if last_anchor is None:
            if first_anchor is not None:
                anchor_id = first_anchor.user.timestamp.isoformat()
                ops.append(InsertOp(message=user_msg, anchor_message_id=anchor_id, insert_before=True))
                ops.append(InsertOp(message=asst_msg, anchor_message_id=anchor_id, insert_before=True))
            else:
                ops.append(InsertOp(message=user_msg, anchor_message_id=None, insert_before=True))
                ops.append(InsertOp(message=asst_msg, anchor_message_id=None, insert_before=True))
        else:
            anchor_id = last_anchor.assistant.timestamp.isoformat()
            ops.append(InsertOp(message=user_msg, anchor_message_id=anchor_id, insert_before=False))
            ops.append(InsertOp(message=asst_msg, anchor_message_id=anchor_id, insert_before=False))

    return ops
