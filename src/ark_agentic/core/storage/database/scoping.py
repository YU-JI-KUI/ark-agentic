"""Agent-scoped ORM access — automatic ``WHERE agent_id = ?`` injection.

A ``do_orm_execute`` listener applies ``with_loader_criteria`` on every
SELECT/UPDATE/DELETE; INSERTs use a ``ContextVar``-backed column default.
Sessions opt in by carrying ``info[_INFO_KEY]``; sessions without it see
every row, which is what cross-agent admin queries need.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator

from sqlalchemy import String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, Session as SyncSession, mapped_column, with_loader_criteria


_INFO_KEY = "ark_agent_id"

_agent_ctx: ContextVar[str | None] = ContextVar("ark_agent_id", default=None)


def _current_agent_id_or_raise() -> str:
    value = _agent_ctx.get()
    if value is None:
        raise RuntimeError(
            "AgentScoped INSERT executed outside an agent_scoped_session — "
            "wrap the write in agent_scoped_session(...) or set agent_id "
            "explicitly."
        )
    return value


class AgentScoped:
    """Mixin tagging an ORM model as partitioned by ``agent_id``."""

    agent_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=_current_agent_id_or_raise,
    )


def _do_orm_execute_filter(execute_state) -> None:
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


event.listen(SyncSession, "do_orm_execute", _do_orm_execute_filter)


@asynccontextmanager
async def agent_scoped_session(
    sessionmaker: async_sessionmaker[AsyncSession],
    agent_id: str,
) -> AsyncIterator[AsyncSession]:
    token = _agent_ctx.set(agent_id)
    try:
        async with sessionmaker() as session:
            session.sync_session.info[_INFO_KEY] = agent_id
            yield session
    finally:
        _agent_ctx.reset(token)
