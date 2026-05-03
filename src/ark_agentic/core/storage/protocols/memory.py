"""MemoryRepository Protocol — heading-structured user memory."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryRepository(Protocol):
    """Heading-structured user memory.

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
        """File 实现忽略 limit/offset。
        SQLite 实现支持 ``limit=None`` (返回全量)。
        PR3 PG 实现下 limit=None 必须 raise ValueError。
        """
        ...
