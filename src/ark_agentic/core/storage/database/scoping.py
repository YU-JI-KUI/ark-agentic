"""Agent-scoped ORM access — automatic ``WHERE agent_id = ?`` injection.

The ``AgentScoped`` mixin tags an ORM model as agent-partitioned. A
session-scoped event listener applies ``with_loader_criteria`` on every
SELECT/UPDATE/DELETE, so individual repository methods never spell
``agent_id`` in WHERE clauses. INSERTs read the same value from a
``ContextVar`` via the column default.

Usage from a repository::

    class SqliteFooRepository:
        def __init__(self, engine, agent_id):
            self._sm = async_sessionmaker(engine, expire_on_commit=False)
            self._agent_id = agent_id

        async def load(self, key):
            async with agent_scoped_session(self._sm, self._agent_id) as s:
                return await s.scalar(select(Foo).where(Foo.key == key))

Cross-agent admin queries open a session **without** the helper and pass
``agent_id`` explicitly — ``with_loader_criteria`` only fires when the
session info carries the scope token, so an unscoped session sees every
row.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator

from sqlalchemy import String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, Session as SyncSession, mapped_column, with_loader_criteria


_INFO_KEY = "ark_agent_id"

# Populated for the duration of a scoped session so column defaults on
# INSERT can pick up the agent_id without each call site passing it.
_agent_ctx: ContextVar[str | None] = ContextVar("ark_agent_id", default=None)


def _current_agent_id_or_raise() -> str:
    value = _agent_ctx.get()
    if value is None:
        raise RuntimeError(
            "AgentScoped INSERT executed outside an agent_scoped_session — "
            "the agent_id default has no value. Wrap the write in "
            "agent_scoped_session(...) or set agent_id explicitly."
        )
    return value


class AgentScoped:
    """Mixin marking an ORM model as partitioned by ``agent_id``.

    The column is NOT NULL with a Python-side default that reads from
    ``_agent_ctx``. Inside ``agent_scoped_session(...)`` the contextvar
    is set, so ``INSERT`` statements that omit ``agent_id`` populate it
    automatically. ``SELECT`` / ``UPDATE`` / ``DELETE`` get a
    ``with_loader_criteria`` filter applied via the session-level event
    listener registered below.
    """

    agent_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=_current_agent_id_or_raise,
    )


def _do_orm_execute_filter(execute_state) -> None:
    """ORM-level event: inject ``agent_id == :ctx`` on every relevant statement.

    Fires for SELECT, UPDATE, and DELETE issued via ``Session.execute()``.
    Sessions that do not opt in (no ``info[_INFO_KEY]``) are left alone
    so cross-agent admin queries can still see every row.
    """
    agent_id = execute_state.session.info.get(_INFO_KEY)
    if agent_id is None:
        return
    if not (
        execute_state.is_select
        or execute_state.is_update
        or execute_state.is_delete
    ):
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            AgentScoped,
            lambda cls: cls.agent_id == agent_id,
            include_aliases=True,
        )
    )


# Register once at import time. The listener is keyed on the session's
# ``info`` dict, so it is harmless on sessions that don't opt in.
event.listen(SyncSession, "do_orm_execute", _do_orm_execute_filter)


@asynccontextmanager
async def agent_scoped_session(
    sessionmaker: async_sessionmaker[AsyncSession],
    agent_id: str,
) -> AsyncIterator[AsyncSession]:
    """Open an ``AsyncSession`` scoped to one ``agent_id``.

    All ORM queries issued through the yielded session are automatically
    filtered by ``agent_id``; INSERTs that omit ``agent_id`` use the
    contextvar-backed default.
    """
    token = _agent_ctx.set(agent_id)
    try:
        async with sessionmaker() as session:
            session.sync_session.info[_INFO_KEY] = agent_id
            yield session
    finally:
        _agent_ctx.reset(token)
