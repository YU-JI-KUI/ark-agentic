"""FileNotificationRepository behavior tests + concurrent mark_read regression."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ark_agentic.core.storage.backends.file.notification import (
    FileNotificationRepository,
)
from ark_agentic.core.storage.protocols import NotificationRepository
from ark_agentic.services.notifications.models import Notification


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    return tmp_path / "notifications"


@pytest.fixture
def repo(base_dir: Path) -> FileNotificationRepository:
    return FileNotificationRepository(base_dir)


def _make_notification(uid: str, user_id: str = "u1") -> Notification:
    return Notification(
        notification_id=uid,
        user_id=user_id,
        job_id="test_job",
        title="t",
        body="b",
    )


async def test_implements_notification_repository_protocol(
    repo: FileNotificationRepository,
):
    assert isinstance(repo, NotificationRepository)


async def test_save_then_list_round_trip(repo: FileNotificationRepository):
    await repo.save(_make_notification("n1"))

    listing = await repo.list_recent("u1")

    assert len(listing.notifications) == 1
    assert listing.notifications[0].notification_id == "n1"


async def test_mark_read_marks_notifications(repo: FileNotificationRepository):
    await repo.save(_make_notification("n1"))
    await repo.save(_make_notification("n2"))

    await repo.mark_read("u1", ["n1"])

    listing = await repo.list_recent("u1")
    by_id = {n.notification_id: n.read for n in listing.notifications}
    assert by_id["n1"] is True
    assert by_id["n2"] is False


async def test_unread_only_filters(repo: FileNotificationRepository):
    await repo.save(_make_notification("n1"))
    await repo.save(_make_notification("n2"))
    await repo.mark_read("u1", ["n1"])

    listing = await repo.list_recent("u1", unread_only=True)

    ids = {n.notification_id for n in listing.notifications}
    assert ids == {"n2"}


async def test_concurrent_mark_read_does_not_lose_ids(
    repo: FileNotificationRepository,
):
    # Arrange: 20 notifications saved
    for i in range(20):
        await repo.save(_make_notification(f"n{i}"))

    # Act: two concurrent mark_read calls on disjoint subsets
    set_a = [f"n{i}" for i in range(10)]
    set_b = [f"n{i}" for i in range(10, 20)]
    await asyncio.gather(
        repo.mark_read("u1", set_a),
        repo.mark_read("u1", set_b),
    )

    # Assert: union is preserved (no lost writes)
    listing = await repo.list_recent("u1", limit=200)
    read_ids = {n.notification_id for n in listing.notifications if n.read}
    assert read_ids == set(set_a) | set(set_b), (
        f"missing={set(set_a + set_b) - read_ids}"
    )
