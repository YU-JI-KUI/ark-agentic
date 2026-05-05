"""Protocol method-set conformance tests.

每个 Protocol 的公开方法集合精确匹配预期，防止误删除/重命名导致后端实现脱钩。
"""

from __future__ import annotations

import inspect

from ark_agentic.core.storage.protocols import (
    MemoryRepository,
    SessionRepository,
)
from ark_agentic.plugins.jobs.protocol import JobRunRepository
from ark_agentic.plugins.notifications.protocol import NotificationRepository


def _public_methods(proto: type) -> set[str]:
    return {
        name for name, _ in inspect.getmembers(proto, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def test_session_repository_method_set():
    expected = {
        "create",
        "append_message",
        "load_messages",
        "update_meta",
        "load_meta",
        "list_session_ids",
        "list_session_metas",
        "list_session_summaries",
        "list_all_sessions",
        "list_all_session_summaries",
        "delete",
        "get_raw_transcript",
        "put_raw_transcript",
        "finalize",
    }

    actual = _public_methods(SessionRepository)

    assert actual == expected, f"missing={expected - actual}, extra={actual - expected}"


def test_memory_repository_method_set():
    expected = {
        "read",
        "upsert_headings",
        "overwrite",
        "list_users",
        "list_memory_summaries",
        "get_last_dream_at",
        "set_last_dream_at",
    }

    actual = _public_methods(MemoryRepository)

    assert actual == expected, f"missing={expected - actual}, extra={actual - expected}"


def test_notification_repository_method_set():
    expected = {"save", "list_recent", "mark_read"}

    actual = _public_methods(NotificationRepository)

    assert actual == expected, f"missing={expected - actual}, extra={actual - expected}"


def test_job_run_repository_method_set():
    expected = {"get_last_run", "set_last_run"}

    actual = _public_methods(JobRunRepository)

    assert actual == expected, f"missing={expected - actual}, extra={actual - expected}"
