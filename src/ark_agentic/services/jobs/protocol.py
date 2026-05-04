"""JobRunRepository Protocol — per-(user, job) last-run timestamp store."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class JobRunRepository(Protocol):
    """Per-(user, job) last-run timestamp store used by the scanner for
    daily idempotency. Internal to the jobs feature; no other subsystem
    should depend on it."""

    async def get_last_run(
        self, user_id: str, job_id: str,
    ) -> float | None:
        """Epoch seconds of the last run, or ``None`` if never run."""
        ...

    async def set_last_run(
        self, user_id: str, job_id: str, timestamp: float,
    ) -> None:
        """Record the time at which (user, job) was last processed."""
        ...
