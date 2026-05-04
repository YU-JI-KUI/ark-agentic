"""Memory 管理器 — 委托层

业务层（runner / tools / extractor / dream）依赖 ``MemoryManager`` 作为
领域抽象；内部委托给 ``MemoryRepository``。后端切换（file / sqlite / pg）
由 ``DB_TYPE`` env 驱动 —— 业务代码完全感知不到。
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from ..storage.protocols import MemoryRepository

logger = logging.getLogger(__name__)


class MemoryConfig(BaseModel):
    """Memory 系统配置。

    保留 ``workspace_dir`` 作为周边模块（scanner / dream marker / agent_state
    rooted）寻址用 —— 即使 SQLite 模式也用作 ``last_dream`` 等 marker 文件根。
    """

    workspace_dir: str = ""


class MemoryManager:
    """轻量 Memory 管理器（委托层）。

    职责：
    - 业务层统一入口，签名稳定
    - 委托所有 R/W 给注入的 ``MemoryRepository``
    - **不暴露文件路径** —— ``memory_path`` 已删，改通过 repository 间接访问
    """

    def __init__(
        self,
        repository: "MemoryRepository",
        config: MemoryConfig | None = None,
    ) -> None:
        self._repo = repository
        self.config = config or MemoryConfig()

    async def read_memory(self, user_id: str) -> str:
        return await self._repo.read(user_id)

    async def write_memory(
        self, user_id: str, content: str,
    ) -> tuple[list[str], list[str]]:
        """Heading-level upsert. Returns (current_headings, dropped_headings)."""
        return await self._repo.upsert_headings(user_id, content)

    async def overwrite(self, user_id: str, content: str) -> None:
        """Full replace — for dream consolidation."""
        await self._repo.overwrite(user_id, content)

    async def list_user_ids(self) -> list[str]:
        return await self._repo.list_users()


def build_memory_manager(
    memory_dir: str | Path | None = None,
) -> MemoryManager:
    """Factory: builds a ``MemoryManager`` whose backend is picked by
    ``DB_TYPE``.

    ``memory_dir`` is required for the file backend; the SQLite backend
    treats it as a logical workspace label (used by adjacent modules
    like the proactive scanner). The directory itself is created lazily
    by ``FileMemoryRepository`` only when file mode is active.
    """
    if memory_dir is None:
        memory_dir = Path(tempfile.gettempdir()) / "ark_memory"
    memory_dir = Path(memory_dir)

    from ..storage.factory import build_memory_repository

    repo = build_memory_repository(workspace_dir=memory_dir)
    return MemoryManager(
        repository=repo,
        config=MemoryConfig(workspace_dir=str(memory_dir)),
    )
