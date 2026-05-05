"""MemoryRepository Protocol — heading-structured user memory."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entries import MemorySummaryEntry


@runtime_checkable
class MemoryRepository(Protocol):
    """Heading-structured user memory, scoped to ONE agent.

    Same ``user_id`` lives independently under each agent.

    DB 实现必须在内部调用 `core.memory.user_profile.parse_heading_sections`
    和 `format_heading_sections` 完成 markdown ⇄ row 转换；这些解析函数
    是共享基础设施，不在 Repository 间重复实现。
    """

    async def read(self, user_id: str) -> str:
        ...

    async def upsert_headings(
        self,
        user_id: str,
        content: str,
    ) -> tuple[list[str], list[str]]:
        ...

    async def overwrite(self, user_id: str, content: str) -> None:
        ...

    async def list_users(
        self,
        limit: int | None = None,
        offset: int = 0,
        order_by_updated_desc: bool = True,
    ) -> list[str]:
        """All backends must honour ``limit/offset``.

        SQLite/PG implementations support ``limit=None`` (returns all).
        PR3 PG: ``limit=None`` must raise on hot paths to force pagination.
        """
        ...

    async def list_memory_summaries(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[MemorySummaryEntry]:
        """Per-user summaries (size + updated_at) for the dashboard listing.

        Resolved in one round-trip — SQLite uses ``length(content)``,
        the file backend reads each MEMORY.md's ``stat()``. Replaces
        ``list_users()`` + N ``read(uid)`` on the dashboard hot path.
        ORDER BY ``updated_at`` DESC.
        """
        ...

    async def get_last_dream_at(self, user_id: str) -> float | None:
        """Epoch seconds when this user's memory was last consolidated.

        Returns ``None`` when no dream has been recorded for the user.
        Internal to the memory subsystem — only ``MemoryDreamer`` reads it.
        """
        ...

    async def set_last_dream_at(
        self, user_id: str, timestamp: float,
    ) -> None:
        """Record the time at which this user's memory was consolidated."""
        ...
