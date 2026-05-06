"""Session storage Protocols — split by responsibility.

The narrow Protocols (``SessionMessageStore`` / ``SessionMetaStore`` /
``SessionTranscriptStore`` / ``SessionAdminStore``) let callers depend on
exactly the slice they need. ``SessionRepository`` aggregates all four
for backends that implement the whole surface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entries import SessionStoreEntry, SessionSummaryEntry
from ...types import AgentMessage


@runtime_checkable
class SessionMessageStore(Protocol):
    """Per-session message append + load + lifecycle hooks.

    PR2+ TODO: ``create()`` is a two-step non-atomic op on the file backend
    (transcript header + meta upsert). DB backends should make it atomic
    via shared-connection transactions or a UnitOfWork — PR1 deliberately
    avoided introducing a UnitOfWork abstraction.
    """

    async def create(
        self,
        session_id: str,
        user_id: str,
        model: str,
        provider: str,
        state: dict,
    ) -> None:
        ...

    async def append_message(
        self,
        session_id: str,
        user_id: str,
        message: AgentMessage,
    ) -> None:
        """Atomically append. No batching, no pending state."""
        ...

    async def load_messages(
        self,
        session_id: str,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AgentMessage]:
        """All backends must honour ``limit/offset``.

        SQLite/PG implementations support ``limit=None`` (returns the full
        session). PR3 PG must raise ``ValueError`` for ``limit=None`` on
        hot paths to force pagination.
        """
        ...

    async def finalize(
        self,
        session_id: str,
        user_id: str,
    ) -> None:
        """Mark session ready for archival.

        File / SQLite / PG: no-op.
        S3 (future): flush in-memory buffer to object storage.

        Business code MUST call this when a session is closed or after a
        compaction completes — the contract that lets a future S3 backend
        slot in without code changes.
        """
        ...


@runtime_checkable
class SessionMetaStore(Protocol):
    """Session metadata (model/provider/tokens/state) + per-user listing.

    Owns the existence of a session row: ``delete()`` lives here so the
    metadata is the source of truth for "does this session exist?".
    """

    async def update_meta(
        self,
        session_id: str,
        user_id: str,
        entry: SessionStoreEntry,
    ) -> None:
        ...

    async def load_meta(
        self,
        session_id: str,
        user_id: str,
    ) -> SessionStoreEntry | None:
        ...

    async def list_session_ids(
        self,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[str]:
        """ORDER BY updated_at DESC. All backends must honour ``limit/offset``."""
        ...

    async def list_session_metas(
        self,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SessionStoreEntry]:
        """List sessions with their full metadata, ORDER BY updated_at DESC.

        Cheaper than ``list_session_ids`` + N ``load_meta`` calls.
        All backends must honour ``limit/offset``.
        """
        ...

    async def delete(
        self,
        session_id: str,
        user_id: str,
    ) -> bool:
        ...


@runtime_checkable
class SessionTranscriptStore(Protocol):
    """Raw JSONL transcript I/O — admin / debug / Studio raw editor.

    Not for the request hot path: implementations may materialise the
    whole transcript to build the JSONL string.
    """

    async def get_raw_transcript(
        self,
        session_id: str,
        user_id: str,
    ) -> str | None:
        """JSONL-formatted transcript.

        DB implementations rebuild the JSONL by full deserialisation —
        admin / debug only.
        """
        ...

    async def put_raw_transcript(
        self,
        session_id: str,
        user_id: str,
        jsonl_content: str,
    ) -> None:
        """Replace transcript wholesale.

        DB implementations must run ``DELETE + INSERT`` in one transaction.
        """
        ...


@runtime_checkable
class SessionAdminStore(Protocol):
    """Cross-user admin queries (Studio "all users" view)."""

    async def list_all_sessions(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[str, str]]:
        """Admin-only: list ``(user_id, session_id)`` across every user.

        ORDER BY updated_at DESC. All backends must honour ``limit/offset``.
        PR3 PG: ``limit=None`` must raise — admin full scans require paging.
        """
        ...

    async def list_session_summaries(
        self,
        user_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SessionSummaryEntry]:
        """Per-session message_count + first user message, one round-trip.

        Replaces "list metas + load every transcript" on the Studio /
        dashboard hot path. Backends MUST resolve count and snippet
        without loading full transcripts:

        - SQLite/PG: correlated scalar subqueries in one statement.
        - File:      sequential JSONL scan stopping at first user message.

        ``user_id=None`` returns an admin cross-user listing (all users).
        ``user_id=<str>`` filters to that user's sessions only.

        ORDER BY ``updated_at`` DESC. ``first_user_message`` is
        truncated to 80 characters, or ``None`` when no user message
        exists yet. All backends must honour ``limit/offset``.
        """
        ...


@runtime_checkable
class SessionRepository(
    SessionMessageStore,
    SessionMetaStore,
    SessionTranscriptStore,
    SessionAdminStore,
    Protocol,
):
    """Aggregate session storage Protocol.

    New code should depend on the narrowest sub-Protocol it needs;
    backends still implement the union.
    """
