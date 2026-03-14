"""External history merge: dedup + anchor-based positioning

Merges externally-provided chat history into the session's unified
message timeline. Pure functions — no side effects, no session mutation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .types import AgentMessage, MessageRole


@dataclass
class InsertOp:
    """Describes where to insert an external message relative to a session anchor."""

    message: AgentMessage
    anchor_message_id: str | None  # timestamp isoformat of anchor; None → append
    insert_before: bool


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


def _session_has_assistant_after(
    session_messages: list[AgentMessage], anchor: AgentMessage
) -> bool:
    """Return True if session already has an assistant message immediately after *anchor*.

    "Immediately after" means the next non-system message following *anchor*.
    This is used to detect the divergent-response scenario: same user turn was
    handled both externally and internally, so the external assistant reply
    should be skipped in favour of the richer internal one.
    """
    found_anchor = False
    for msg in session_messages:
        if msg is anchor:
            found_anchor = True
            continue
        if found_anchor:
            # Skip any system messages between anchor and next real message
            if msg.role == MessageRole.SYSTEM:
                continue
            return msg.role == MessageRole.ASSISTANT
    return False


def merge_external_history(
    session_messages: list[AgentMessage],
    raw_history: list[dict[str, Any]],
    *,
    short_threshold: float = 0.75,
    long_threshold: float = 0.85,
) -> list[InsertOp]:
    """Compute InsertOps to merge *raw_history* into *session_messages*.

    Returns a list of :class:`InsertOp` — the caller (SessionManager) is
    responsible for resolving ``anchor_message_id`` to an actual index and
    performing the insertion.

    Structural pair check: if an external assistant message immediately follows
    a matched user anchor, and the session already has an assistant message
    right after that anchor, the external assistant is skipped. This prevents
    injecting a divergent reply into an already-completed internal turn.
    """
    if not raw_history:
        return []

    # 1. Build dedup window: user/assistant messages from session tail
    comparable = [
        m for m in session_messages
        if m.role in (MessageRole.USER, MessageRole.ASSISTANT)
    ]
    window = comparable[-len(raw_history) :] if comparable else []

    # 2. Find anchors: external msg ↔ session msg (same role + similar content)
    #    anchor_map: index-in-raw_history → matched session AgentMessage
    anchor_map: dict[int, AgentMessage] = {}
    used_window: set[int] = set()  # prevent one session msg matching twice

    for ei, ext in enumerate(raw_history):
        ext_role = ext.get("role", "")
        ext_content = ext.get("content", "")
        for wi, win_msg in enumerate(window):
            if wi in used_window:
                continue
            if ext_role != win_msg.role.value:
                continue
            if is_duplicate(
                ext_content,
                win_msg.content or "",
                short_threshold=short_threshold,
                long_threshold=long_threshold,
            ):
                anchor_map[ei] = win_msg
                used_window.add(wi)
                break

    # Fast path: all duplicates → nothing to insert
    if len(anchor_map) == len(raw_history):
        return []

    # 3. Walk raw_history, emit InsertOps relative to anchors
    ops: list[InsertOp] = []
    last_anchor: AgentMessage | None = None

    # Pre-scan: find first anchor (needed for "before first anchor" case)
    first_anchor: AgentMessage | None = None
    for ei in range(len(raw_history)):
        if ei in anchor_map:
            first_anchor = anchor_map[ei]
            break

    for ei, ext in enumerate(raw_history):
        if ei in anchor_map:
            last_anchor = anchor_map[ei]
            continue

        ext_role = ext.get("role", "")

        # Structural pair check: skip external assistant that immediately follows
        # a matched user anchor when the internal session has already handled
        # that turn (i.e. an assistant message already exists after the anchor).
        if (
            ext_role == MessageRole.ASSISTANT.value
            and last_anchor is not None
            and last_anchor.role == MessageRole.USER
            and _session_has_assistant_after(session_messages, last_anchor)
        ):
            continue

        msg = AgentMessage(
            role=MessageRole(ext_role),
            content=ext.get("content", ""),
            metadata={"source": "external"},
        )

        if last_anchor is None:
            # Before any anchor (or no anchors at all)
            if first_anchor is not None:
                ops.append(InsertOp(
                    message=msg,
                    anchor_message_id=first_anchor.timestamp.isoformat(),
                    insert_before=True,
                ))
            else:
                ops.append(InsertOp(
                    message=msg,
                    anchor_message_id=None,
                    insert_before=True,
                ))
        else:
            # After the most recent anchor
            ops.append(InsertOp(
                message=msg,
                anchor_message_id=last_anchor.timestamp.isoformat(),
                insert_before=False,
            ))

    return ops
