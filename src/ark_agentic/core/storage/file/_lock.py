"""Cross-platform async file lock — private to the file-backend session repository."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

if sys.platform != "win32":
    import fcntl
else:
    fcntl = None  # type: ignore

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_MS = 10_000
LOCK_POLL_INTERVAL_MS = 25
LOCK_STALE_MS = 30_000


class FileLock:
    """文件锁（跨平台）

    参考: openclaw-main/src/config/sessions/store.ts - withSessionStoreLock

    在 Windows 上使用文件存在性作为锁机制，
    在 Unix 上使用更可靠的 O_EXCL 文件创建。
    """

    def __init__(
        self,
        lock_path: str | Path,
        timeout_ms: int = LOCK_TIMEOUT_MS,
        poll_interval_ms: int = LOCK_POLL_INTERVAL_MS,
        stale_ms: int = LOCK_STALE_MS,
    ):
        self.lock_path = Path(lock_path)
        self.timeout_ms = timeout_ms
        self.poll_interval_ms = poll_interval_ms
        self.stale_ms = stale_ms
        self._fd: int | None = None
        self._file_handle: Any = None

    async def acquire(self) -> bool:
        """获取锁"""
        start_time = time.time() * 1000
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                if sys.platform == "win32":
                    # Windows: 使用文件存在性检查 + 写锁
                    if self.lock_path.exists():
                        # 检查锁是否过期
                        now = time.time() * 1000
                        try:
                            stat = self.lock_path.stat()
                            age_ms = now - (stat.st_mtime * 1000)
                            if age_ms > self.stale_ms:
                                # 删除过期锁
                                self.lock_path.unlink(missing_ok=True)
                            else:
                                if now - start_time > self.timeout_ms:
                                    logger.warning(f"锁获取超时: {self.lock_path}")
                                    return False
                                await asyncio.sleep(self.poll_interval_ms / 1000)
                                continue
                        except (OSError, FileNotFoundError):
                            pass

                    # 尝试创建锁文件
                    lock_info = json.dumps(
                        {"pid": os.getpid(), "startedAt": int(time.time() * 1000)}
                    )
                    self._file_handle = open(self.lock_path, "x", encoding="utf-8")
                    self._file_handle.write(lock_info)
                    self._file_handle.flush()
                    return True
                else:
                    # Unix: 使用 O_EXCL 创建
                    self._fd = os.open(
                        str(self.lock_path),
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o600,
                    )
                    lock_info = json.dumps(
                        {"pid": os.getpid(), "startedAt": int(time.time() * 1000)}
                    )
                    os.write(self._fd, lock_info.encode())
                    return True

            except FileExistsError:
                # 锁已存在
                now = time.time() * 1000
                if now - start_time > self.timeout_ms:
                    logger.warning(f"锁获取超时: {self.lock_path}")
                    return False

                # 检查锁是否过期
                try:
                    stat = self.lock_path.stat()
                    age_ms = now - (stat.st_mtime * 1000)
                    if age_ms > self.stale_ms:
                        # 删除过期锁
                        self.lock_path.unlink(missing_ok=True)
                        continue
                except (OSError, FileNotFoundError):
                    pass

                # 等待后重试
                await asyncio.sleep(self.poll_interval_ms / 1000)
            except OSError as e:
                logger.error(f"锁获取失败: {e}")
                return False

    def release(self) -> None:
        """释放锁"""
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

        if self._file_handle is not None:
            try:
                self._file_handle.close()
            except OSError:
                pass
            self._file_handle = None

        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    async def __aenter__(self) -> FileLock:
        if not await self.acquire():
            raise TimeoutError(f"无法获取锁: {self.lock_path}")
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()
