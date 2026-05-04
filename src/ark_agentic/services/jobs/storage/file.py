"""FileJobRunRepository — per-(user, job) dotfile last-run store.

Layout: ``{base_dir}/{user_id}/.{job_id}`` (text file containing the
epoch-second timestamp). Parallels the file backends used elsewhere
(memory's ``.last_dream``); writes are atomic via tmp + rename.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path


class FileJobRunRepository:
    """File-backed implementation of JobRunRepository."""

    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    def _path(self, user_id: str, job_id: str) -> Path:
        return self._base_dir / user_id / f".{job_id}"

    async def get_last_run(
        self, user_id: str, job_id: str,
    ) -> float | None:
        return await asyncio.to_thread(self._get_sync, user_id, job_id)

    def _get_sync(self, user_id: str, job_id: str) -> float | None:
        path = self._path(user_id, job_id)
        if not path.exists():
            return None
        try:
            return float(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    async def set_last_run(
        self, user_id: str, job_id: str, timestamp: float,
    ) -> None:
        await asyncio.to_thread(
            self._set_sync, user_id, job_id, timestamp,
        )

    def _set_sync(
        self, user_id: str, job_id: str, timestamp: float,
    ) -> None:
        target = self._path(user_id, job_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target.parent),
            prefix=".jobrun_",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(str(timestamp))
            tmp_path = tmp.name
        os.replace(tmp_path, target)
