"""Job-run repository factory — env-driven backend dispatch.

Self-contained: the jobs feature owns its backend selection so core
does not know the storage layout. ``AsyncEngine`` lives in
``services/jobs/engine.py``; this factory never sees it directly.
"""

from __future__ import annotations

import os
from pathlib import Path

from .protocol import JobRunRepository
from .storage.file import FileJobRunRepository
from .storage.sqlite import SqliteJobRunRepository


def _resolve_db_type() -> str:
    raw = os.environ.get("DB_TYPE", "file").strip().lower()
    if raw not in ("file", "sqlite"):
        raise ValueError(
            f"Unsupported DB_TYPE={raw!r}; expected 'file' or 'sqlite'"
        )
    return raw


def build_job_run_repository(
    base_dir: str | Path | None = None,
) -> JobRunRepository:
    """Build a ``JobRunRepository`` backed by the configured DB_TYPE.

    File backend requires ``base_dir`` (rooted at ``get_job_runs_base_dir()``
    for the canonical scanner usage). SQLite backend ignores it: rows
    are partitioned by the (user_id, job_id) PK.
    """
    db_type = _resolve_db_type()
    if db_type == "file":
        if base_dir is None:
            raise ValueError(
                "JobRunRepository requires 'base_dir' when DB_TYPE=file."
            )
        return FileJobRunRepository(Path(base_dir))
    if db_type == "sqlite":
        from .engine import get_engine
        return SqliteJobRunRepository(get_engine())
    raise ValueError(
        f"Unsupported DB_TYPE for job-run repository: {db_type!r}"
    )
