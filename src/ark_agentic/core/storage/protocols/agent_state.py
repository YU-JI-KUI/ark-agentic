"""AgentStateRepository Protocol — per-user keyed agent markers (last_dream, last_job_*)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentStateRepository(Protocol):
    """Per-user keyed agent state markers.

    PR1 File 实现：`{workspace}/{user_id}/.{key}` 文本文件。
    PR2+ DB 实现：`agent_state(user_id, key)` 复合主键表。
    """

    async def get(self, user_id: str, key: str) -> str | None:
        ...

    async def set(self, user_id: str, key: str, value: str) -> None:
        ...

    async def list_users_with_key(
        self,
        key: str,
        limit: int | None = None,
        offset: int = 0,
        order_by_updated_desc: bool = True,
    ) -> list[tuple[str, str]]:
        """File 实现忽略 limit/offset；DB 实现下 limit=None 必须 raise ValueError。"""
        ...
