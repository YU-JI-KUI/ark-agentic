"""SessionRepository Protocol — per-agent session storage abstraction."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ...persistence import SessionStoreEntry
from ...types import AgentMessage


@runtime_checkable
class SessionRepository(Protocol):
    """Per-agent session storage abstraction.

    PR2+ TODO: create() 在 File 实现下是两步非原子操作 (transcript header
    + meta upsert)。DB 实现需要通过共享 engine connection 或 UnitOfWork
    保证原子性 —— PR1 有意不引入 UnitOfWork 抽象避免过早设计。
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
        """File 实现忽略 limit/offset。
        SQLite 实现支持 ``limit=None`` (返回全量，单进程嵌入式 DB 下成本可接受)。
        PR3 PG 实现下 limit=None 必须 raise ValueError，强制热路径分页。
        """
        ...

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
        """ORDER BY updated_at DESC.
        SQLite 实现支持 ``limit=None`` (返回全量)。
        PR3 PG 实现下 limit=None 必须 raise ValueError。
        """
        ...

    async def list_session_metas(
        self,
        user_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SessionStoreEntry]:
        """List sessions with their full metadata, ORDER BY updated_at DESC.

        Cheaper than ``list_session_ids`` + N ``load_meta`` calls.
        SQLite 实现支持 ``limit=None`` (返回全量)。
        PR3 PG 实现下 limit=None 必须 raise ValueError。
        """
        ...

    async def list_all_sessions(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[str, str]]:
        """Admin-only: list ``(user_id, session_id)`` across every user.

        ORDER BY updated_at DESC. Used by Studio "all users" admin view.
        File 实现忽略 limit/offset。
        SQLite 实现支持 ``limit=None`` (返回全量)。
        PR3 PG 实现下 limit=None 必须 raise ValueError —— admin 全量扫描
        在 PG 下必须翻页。
        """
        ...

    async def delete(
        self,
        session_id: str,
        user_id: str,
    ) -> bool:
        ...

    async def get_raw_transcript(
        self,
        session_id: str,
        user_id: str,
    ) -> str | None:
        """JSONL-formatted transcript.

        DB 实现已知权衡：全量反序列化拼接，仅供低频管理操作 (Studio raw editor /
        debug 导出)；不得在请求热路径调用。
        """
        ...

    async def put_raw_transcript(
        self,
        session_id: str,
        user_id: str,
        jsonl_content: str,
    ) -> None:
        """Replace transcript wholesale.

        DB 实现必须在单事务内完成 DELETE + INSERT。如果调用方同时需要更新 meta，
        须由调用方组织 UnitOfWork (PR2+)；PR1 File 实现不强制此约束。
        """
        ...

    async def finalize(
        self,
        session_id: str,
        user_id: str,
    ) -> None:
        """Mark session ready for archival.

        File/SQLite/PG: no-op。
        S3 (未来): 把内存缓冲一次性 PUT 到对象存储。

        **业务代码必须在 session 关闭/compact 完成后调用此方法**。
        Task 16 在 runner._finalize_run 和 session.compact_session 接入此调用。
        这是"零代码升级到 S3"的契约边界。
        """
        ...
