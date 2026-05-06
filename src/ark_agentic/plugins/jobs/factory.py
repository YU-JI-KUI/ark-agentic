"""Job-run repository factory — mode-driven backend dispatch.

Self-contained: the jobs feature owns its backend selection so core
does not know the storage layout. ``AsyncEngine`` lives in
``services/jobs/engine.py``; this factory never sees it directly.
"""

from __future__ import annotations

from pathlib import Path

from ...core.storage import mode
from .protocol import JobRunRepository
from .storage.file import FileJobRunRepository
from .storage.sqlite import SqliteJobRunRepository


def build_job_run_repository(
    base_dir: str | Path | None = None,
) -> JobRunRepository:
    """Build a ``JobRunRepository`` backed by the configured storage mode.

    File backend requires ``base_dir`` (rooted at ``get_job_runs_base_dir()``
    for the canonical scanner usage). SQLite backend ignores it: rows
    are partitioned by the (user_id, job_id) PK.
    """
    active = mode.current()
    if active == "file":
        if base_dir is None:
            raise ValueError(
                "JobRunRepository requires 'base_dir' when DB_TYPE=file."
            )
        return FileJobRunRepository(Path(base_dir))
    if active == "sqlite":
        from .engine import get_engine
        return SqliteJobRunRepository(get_engine())
    raise ValueError(
        f"Unsupported storage mode for job-run repository: {active!r}"
    )
