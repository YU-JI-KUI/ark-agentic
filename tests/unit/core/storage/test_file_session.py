"""FileSessionRepository behavior tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ark_agentic.core.storage.entries import SessionStoreEntry
from ark_agentic.core.storage.repository.file.session import FileSessionRepository
from ark_agentic.core.storage.protocols import SessionRepository
from ark_agentic.core.types import AgentMessage, MessageRole


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    return tmp_path / "sessions"


@pytest.fixture
def repo(sessions_dir: Path) -> FileSessionRepository:
    return FileSessionRepository(sessions_dir)


def _msg(text: str, role: MessageRole = MessageRole.USER) -> AgentMessage:
    return AgentMessage(role=role, content=text, timestamp=datetime.now())


async def test_implements_session_repository_protocol(repo: FileSessionRepository):
    assert isinstance(repo, SessionRepository)


async def test_create_initializes_transcript_and_meta(
    repo: FileSessionRepository,
):
    await repo.create("s1", "u1", model="m", provider="p", state={"k": "v"})

    meta = await repo.load_meta("s1", "u1")
    assert meta is not None
    assert meta.model == "m"
    assert meta.state == {"k": "v"}


async def test_append_then_load_round_trip(repo: FileSessionRepository):
    await repo.create("s1", "u1", model="m", provider="p", state={})

    await repo.append_message("s1", "u1", _msg("hello"))
    await repo.append_message("s1", "u1", _msg("world", MessageRole.ASSISTANT))

    msgs = await repo.load_messages("s1", "u1")
    assert [m.content for m in msgs] == ["hello", "world"]


async def test_list_session_ids_returns_user_sessions(
    repo: FileSessionRepository,
):
    await repo.create("s1", "u1", model="m", provider="p", state={})
    await repo.create("s2", "u1", model="m", provider="p", state={})
    await repo.create("s3", "u2", model="m", provider="p", state={})

    sessions = await repo.list_session_ids("u1")

    assert set(sessions) == {"s1", "s2"}


async def test_get_put_raw_transcript_round_trip(repo: FileSessionRepository):
    await repo.create("s1", "u1", model="m", provider="p", state={})
    await repo.append_message("s1", "u1", _msg("hi"))

    raw = await repo.get_raw_transcript("s1", "u1")
    assert raw is not None
    assert "hi" in raw

    await repo.put_raw_transcript("s1", "u1", raw)
    again = await repo.get_raw_transcript("s1", "u1")
    assert again == (raw if raw.endswith("\n") else raw + "\n")


async def test_delete_clears_transcript_and_meta(repo: FileSessionRepository):
    await repo.create("s1", "u1", model="m", provider="p", state={})
    await repo.append_message("s1", "u1", _msg("x"))

    deleted = await repo.delete("s1", "u1")

    assert deleted is True
    assert await repo.load_meta("s1", "u1") is None
    assert await repo.get_raw_transcript("s1", "u1") is None


async def test_finalize_is_noop(repo: FileSessionRepository):
    await repo.create("s1", "u1", model="m", provider="p", state={})

    # Must not raise; file backend has nothing to flush.
    await repo.finalize("s1", "u1")
