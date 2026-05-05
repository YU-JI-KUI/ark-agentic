"""FileMemoryRepository — file-backed MemoryRepository implementation.

布局：``{workspace}/{user_id}/MEMORY.md``。负责所有 sync 文件 I/O，业务层
应通过 ``MemoryManager``（委托层）访问而不是直接调用此类。
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from ...memory.user_profile import (
    format_heading_sections,
    parse_heading_sections,
)
from ._paginate import paginate

logger = logging.getLogger(__name__)

_PROFILE_FILENAME = "MEMORY.md"
_LAST_DREAM_FILENAME = ".last_dream"


class FileMemoryRepository:
    """File-backed implementation of MemoryRepository."""

    def __init__(self, workspace_dir: str | Path) -> None:
        self._workspace = Path(workspace_dir)
        self._workspace.mkdir(parents=True, exist_ok=True)

    def _memory_path(self, user_id: str) -> Path:
        return self._workspace / user_id / _PROFILE_FILENAME

    async def read(self, user_id: str) -> str:
        return await asyncio.to_thread(self._read_sync, user_id)

    def _read_sync(self, user_id: str) -> str:
        path = self._memory_path(user_id)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    async def upsert_headings(
        self,
        user_id: str,
        content: str,
    ) -> tuple[list[str], list[str]]:
        return await asyncio.to_thread(self._upsert_headings_sync, user_id, content)

    def _upsert_headings_sync(
        self,
        user_id: str,
        content: str,
    ) -> tuple[list[str], list[str]]:
        """Heading-level upsert. Returns (current_headings, dropped_headings).

        Empty-body headings trigger deletion (format drops them via ``if c``).
        Returns ``([], [])`` if content contains no ``##`` headings.
        """
        path = self._memory_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        prev_preamble, prev_sections = parse_heading_sections(existing)
        _, incoming = parse_heading_sections(content)

        if not incoming:
            return [], []

        merged = {**prev_sections, **incoming}
        path.write_text(
            format_heading_sections(prev_preamble, merged), encoding="utf-8",
        )

        current = [k for k, v in merged.items() if v]
        dropped = sorted(set(prev_sections) - set(current))
        logger.info(
            "upsert_headings for %s: headings=%s, dropped=%s",
            user_id, current, dropped,
        )
        return current, dropped

    async def overwrite(self, user_id: str, content: str) -> None:
        await asyncio.to_thread(self._overwrite_sync, user_id, content)

    def _overwrite_sync(self, user_id: str, content: str) -> None:
        target = self._memory_path(user_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        # tmp + rename for atomicity
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target.parent),
            prefix=".memory_",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        os.replace(tmp_path, target)

    def _last_dream_path(self, user_id: str) -> Path:
        return self._workspace / user_id / _LAST_DREAM_FILENAME

    async def get_last_dream_at(self, user_id: str) -> float | None:
        return await asyncio.to_thread(self._get_last_dream_at_sync, user_id)

    def _get_last_dream_at_sync(self, user_id: str) -> float | None:
        path = self._last_dream_path(user_id)
        if not path.exists():
            return None
        try:
            return float(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    async def set_last_dream_at(
        self, user_id: str, timestamp: float,
    ) -> None:
        await asyncio.to_thread(
            self._set_last_dream_at_sync, user_id, timestamp,
        )

    def _set_last_dream_at_sync(
        self, user_id: str, timestamp: float,
    ) -> None:
        target = self._last_dream_path(user_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target.parent),
            prefix=".last_dream_",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(str(timestamp))
            tmp_path = tmp.name
        os.replace(tmp_path, target)

    async def list_users(
        self,
        limit: int | None = None,
        offset: int = 0,
        order_by_updated_desc: bool = True,
    ) -> list[str]:
        return await asyncio.to_thread(
            self._list_users_sync, limit, offset, order_by_updated_desc,
        )

    def _list_users_sync(
        self,
        limit: int | None,
        offset: int,
        order_by_updated_desc: bool,
    ) -> list[str]:
        if not self._workspace.exists():
            return []
        users_with_mtime: list[tuple[str, float]] = []
        for entry in self._workspace.iterdir():
            if not entry.is_dir():
                continue
            mem = entry / _PROFILE_FILENAME
            if not mem.exists():
                continue
            users_with_mtime.append((entry.name, mem.stat().st_mtime))
        users_with_mtime.sort(key=lambda t: t[1], reverse=order_by_updated_desc)
        names = [name for name, _ in users_with_mtime]
        return paginate(names, limit, offset)
