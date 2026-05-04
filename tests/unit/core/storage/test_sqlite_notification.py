"""SqliteNotificationRepository behavior tests + concurrent mark_read regression."""

from __future__ import annotations

import asyncio

import pytest

from ark_agentic.core.db.config import DBConfig
from ark_agentic.core.db.engine import (
    get_async_engine,
    reset_engine_cache,
)
from ark_agentic.services.notifications.engine import (
    init_schema as init_notif_schema,
)
from ark_agentic.services.notifications.models import Notification
from ark_agentic.services.notifications.protocol import NotificationRepository
from ark_agentic.services.notifications.storage.sqlite import (
    SqliteNotificationRepository,
)


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    reset_engine_cache()
    yield
    reset_engine_cache()


@pytest.fixture
async def repo() -> SqliteNotificationRepository:
    cfg = DBConfig(
        db_type="sqlite", connection_str="sqlite+aiosqlite:///:memory:",
    )
    engine = get_async_engine(cfg)
    # Inject as the process engine so notifications' init_schema picks it up.
    from ark_agentic.core.db.engine import set_engine_for_testing
    set_engine_for_testing(engine)
    await init_notif_schema()
    return SqliteNotificationRepository(engine)


def _make_notification(uid: str, user_id: str = "u1") -> Notification:
    return Notification(
        notification_id=uid,
        user_id=user_id,
        job_id="test_job",
        title="t",
        body="b",
    )


async def test_implements_notification_repository_protocol(
    repo: SqliteNotificationRepository,
):
    assert isinstance(repo, NotificationRepository)


async def test_save_then_list_round_trip(repo: SqliteNotificationRepository):
    await repo.save(_make_notification("n1"))

    listing = await repo.list_recent("u1")

    assert len(listing.notifications) == 1
    assert listing.notifications[0].notification_id == "n1"


async def test_mark_read_marks_notifications(repo: SqliteNotificationRepository):
    await repo.save(_make_notification("n1"))
    await repo.save(_make_notification("n2"))

    await repo.mark_read("u1", ["n1"])

    listing = await repo.list_recent("u1")
    by_id = {n.notification_id: n.read for n in listing.notifications}
    assert by_id["n1"] is True
    assert by_id["n2"] is False


async def test_unread_only_filters(repo: SqliteNotificationRepository):
    await repo.save(_make_notification("n1"))
    await repo.save(_make_notification("n2"))
    await repo.mark_read("u1", ["n1"])

    listing = await repo.list_recent("u1", unread_only=True)

    ids = {n.notification_id for n in listing.notifications}
    assert ids == {"n2"}


async def test_concurrent_mark_read_does_not_lose_ids(
    repo: SqliteNotificationRepository,
):
    for i in range(20):
        await repo.save(_make_notification(f"n{i}"))

    set_a = [f"n{i}" for i in range(10)]
    set_b = [f"n{i}" for i in range(10, 20)]
    await asyncio.gather(
        repo.mark_read("u1", set_a),
        repo.mark_read("u1", set_b),
    )

    listing = await repo.list_recent("u1", limit=200)
    read_ids = {n.notification_id for n in listing.notifications if n.read}
    assert read_ids == set(set_a) | set(set_b), (
        f"missing={set(set_a + set_b) - read_ids}"
    )


async def test_list_recent_paging_returns_only_page_slice(
    repo: SqliteNotificationRepository,
):
    """``list_recent`` must page in SQL — not return all rows then slice.

    Counts (total/unread) reflect the full visible set so the UI can show
    'X of Y' even when the page is small.
    """
    for i in range(15):
        await repo.save(_make_notification(f"n{i:02d}"))
    await repo.mark_read("u1", ["n00", "n01", "n02"])

    page = await repo.list_recent("u1", limit=5, offset=0)

    assert len(page.notifications) == 5, "page must respect limit"
    assert page.total == 15, "total must reflect full set, not page"
    assert page.unread_count == 12, "unread_count must reflect full set"


async def test_list_recent_unread_only_paging(
    repo: SqliteNotificationRepository,
):
    """unread_only filters in SQL; counts remain on the full set."""
    for i in range(10):
        await repo.save(_make_notification(f"n{i:02d}"))
    await repo.mark_read("u1", ["n00", "n01"])

    page = await repo.list_recent("u1", limit=3, offset=0, unread_only=True)

    assert len(page.notifications) == 3
    assert all(not n.read for n in page.notifications)
    assert page.total == 10
    assert page.unread_count == 8


async def test_save_is_idempotent_on_duplicate_id(
    repo: SqliteNotificationRepository,
):
    """Re-saving the same notification_id must not raise IntegrityError."""
    n = _make_notification("n1")
    await repo.save(n)
    await repo.save(n)

    listing = await repo.list_recent("u1")
    assert len(listing.notifications) == 1
