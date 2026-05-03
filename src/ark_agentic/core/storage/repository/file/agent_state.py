"""FileAgentStateRepository — per-user keyed marker files.

布局：{workspace}/{user_id}/.{key}  (例如 .last_dream / .last_job_X)
PR2 SQLite 实现：agent_state(user_id, key) 复合主键 + value TEXT 列。
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path


class FileAgentStateRepository:
    """File-backed implementation of AgentStateRepository."""

    def __init__(self, workspace: str | Path) -> None:
        self._workspace = Path(workspace)

    def _user_dir(self, user_id: str) -> Path:
        return self._workspace / user_id

    def _key_path(self, user_id: str, key: str) -> Path:
        return self._user_dir(user_id) / f".{key}"

    async def get(self, user_id: str, key: str) -> str | None:
        return await asyncio.to_thread(self._get_sync, user_id, key)

    def _get_sync(self, user_id: str, key: str) -> str | None:
        p = self._key_path(user_id, key)
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8")

    async def set(self, user_id: str, key: str, value: str) -> None:
        await asyncio.to_thread(self._set_sync, user_id, key, value)

    def _set_sync(self, user_id: str, key: str, value: str) -> None:
        target = self._key_path(user_id, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # tmp + rename for atomicity
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target.parent),
            prefix=".state_",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(value)
            tmp_path = tmp.name
        os.replace(tmp_path, target)

    async def list_users_with_key(
        self,
        key: str,
        limit: int | None = None,
        offset: int = 0,
        order_by_updated_desc: bool = True,
    ) -> list[tuple[str, str]]:
        return await asyncio.to_thread(
            self._list_users_with_key_sync, key, order_by_updated_desc
        )

    def _list_users_with_key_sync(
        self,
        key: str,
        order_by_updated_desc: bool,
    ) -> list[tuple[str, str]]:
        if not self._workspace.exists():
            return []
        results: list[tuple[str, str, float]] = []
        for entry in self._workspace.iterdir():
            if not entry.is_dir():
                continue
            kp = entry / f".{key}"
            if not kp.exists():
                continue
            value = kp.read_text(encoding="utf-8")
            results.append((entry.name, value, kp.stat().st_mtime))
        results.sort(key=lambda t: t[2], reverse=order_by_updated_desc)
        return [(name, value) for name, value, _ in results]
