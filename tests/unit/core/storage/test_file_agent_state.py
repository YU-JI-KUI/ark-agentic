"""FileAgentStateRepository 行为测试。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ark_agentic.core.storage.repository.file.agent_state import FileAgentStateRepository
from ark_agentic.core.storage.protocols import AgentStateRepository


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def repo(workspace: Path) -> FileAgentStateRepository:
    return FileAgentStateRepository(workspace)


async def test_implements_agent_state_repository_protocol(
    repo: FileAgentStateRepository,
):
    assert isinstance(repo, AgentStateRepository)


async def test_get_returns_none_when_missing(repo: FileAgentStateRepository):
    result = await repo.get("alice", "last_dream")

    assert result is None


async def test_set_then_get_round_trip(repo: FileAgentStateRepository):
    await repo.set("bob", "last_dream", "1234567890")

    result = await repo.get("bob", "last_dream")
    assert result == "1234567890"


async def test_set_overwrites_previous_value(repo: FileAgentStateRepository):
    await repo.set("carol", "last_job_x", "1")
    await repo.set("carol", "last_job_x", "2")

    assert await repo.get("carol", "last_job_x") == "2"


async def test_key_with_dots_is_supported(repo: FileAgentStateRepository):
    await repo.set("dave", "last_job_send.notify", "ts")

    assert await repo.get("dave", "last_job_send.notify") == "ts"


async def test_list_users_with_key_filters_by_key(
    repo: FileAgentStateRepository, workspace: Path
):
    await repo.set("u1", "last_dream", "1")
    await repo.set("u2", "last_dream", "2")
    await repo.set("u3", "last_job_x", "3")  # different key

    users = await repo.list_users_with_key("last_dream")

    names = {u for u, _ in users}
    assert names == {"u1", "u2"}


async def test_list_users_with_key_orders_by_mtime_desc(
    repo: FileAgentStateRepository,
):
    await repo.set("oldest", "last_dream", "1")
    time.sleep(0.05)
    await repo.set("middle", "last_dream", "2")
    time.sleep(0.05)
    await repo.set("newest", "last_dream", "3")

    users = await repo.list_users_with_key("last_dream", order_by_updated_desc=True)

    names = [u for u, _ in users]
    assert names == ["newest", "middle", "oldest"]
