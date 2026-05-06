"""Memory 管理器 — 委托层 + 进程内活跃用户缓存

业务层（runner / tools / extractor）依赖 ``MemoryManager`` 作为领域抽象；
内部委托给 ``MemoryRepository``。后端切换（file / sqlite / pg）由 ``DB_TYPE``
env 驱动 —— 业务代码完全感知不到。

子系统封箱：``MemoryDreamer`` 是 memory 子系统的内部组件，由
``MemoryManager`` 在 ``enable_dream=True`` 时按需构造并持有。外部只通过
``maybe_consolidate(user_id)`` 触发蒸馏，不感知 dreamer 的存在。

Active-user cache: ``MemoryManager`` 持有 ``_memory: dict[user_id, str]``
镜像，与 ``SessionManager._sessions`` 同模式 —— 单 worker 下重复读直接命
中内存。多 worker / Redis 共享缓存留给 PG/Redis 里程碑统一引入。
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from pydantic import BaseModel

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from ..session import SessionManager
    from ..storage.entries import MemorySummaryEntry
    from ..storage.protocols import MemoryRepository
    from .dream import MemoryDreamer

logger = logging.getLogger(__name__)


class MemoryConfig(BaseModel):
    """Memory 系统配置。

    ``workspace_dir`` 是周边模块（scanner / proactive setup）寻址用的
    逻辑标签；即使 SQLite 后端也保留以便业务代码稳定。

    Dreaming 相关字段控制后台蒸馏：``enable_dream=False`` 时
    ``maybe_consolidate`` 完全是 no-op，``MemoryManager`` 也不会构造内部
    dreamer。
    """

    workspace_dir: str = ""
    enable_dream: bool = False
    dream_min_hours: float = 24.0
    dream_min_sessions: int = 3


class MemoryManager:
    """轻量 Memory 管理器（委托层 + dreamer 容器）。

    职责：
    - 业务层统一入口，签名稳定
    - 委托所有 R/W 给注入的 ``MemoryRepository``
    - 内存镜像活跃用户的 memory 内容，避免每个 chat turn 都打 I/O
    - **不暴露文件路径** —— 通过 repository 间接访问
    - 内部构造 / 持有 ``MemoryDreamer``；外部仅通过
      ``maybe_consolidate(user_id)`` 触发
    """

    def __init__(
        self,
        repository: "MemoryRepository",
        config: MemoryConfig | None = None,
        *,
        session_manager: "SessionManager | None" = None,
        llm_factory: "Callable[[], BaseChatModel] | None" = None,
    ) -> None:
        self._repo = repository
        self.config = config or MemoryConfig()
        # In-memory mirror; same shape as SessionManager._sessions.
        # Process-local; restart clears.
        self._memory: dict[str, str] = {}

        self._session_manager = session_manager
        self._dreamer: "MemoryDreamer | None" = None
        if self.config.enable_dream:
            if session_manager is None or llm_factory is None:
                raise ValueError(
                    "MemoryConfig.enable_dream=True requires session_manager "
                    "and llm_factory at MemoryManager construction."
                )
            from .dream import MemoryDreamer

            self._dreamer = MemoryDreamer(
                llm_factory,
                memory_manager=self,
                session_manager=session_manager,
                memory_repo=repository,
                min_hours=self.config.dream_min_hours,
                min_sessions=self.config.dream_min_sessions,
            )

    async def read_memory(self, user_id: str) -> str:
        if user_id in self._memory:
            return self._memory[user_id]
        content = await self._repo.read(user_id)
        # Cache empty strings too: cold users would otherwise re-hit the
        # backend on every chat turn.
        self._memory[user_id] = content
        return content

    async def write_memory(
        self, user_id: str, content: str,
    ) -> tuple[list[str], list[str]]:
        """Heading-level upsert. Returns (current_headings, dropped_headings).

        Cache is invalidated, not updated: the merged content is computed
        in the repository, and re-reading once is cheaper than mirroring
        the merge logic here.
        """
        result = await self._repo.upsert_headings(user_id, content)
        self._memory.pop(user_id, None)
        return result

    async def overwrite(self, user_id: str, content: str) -> None:
        """Full replace — for dream consolidation. Cache eagerly populated."""
        await self._repo.overwrite(user_id, content)
        self._memory[user_id] = content

    async def list_user_ids(self) -> list[str]:
        return await self._repo.list_users()

    async def list_memory_summaries(self) -> list["MemorySummaryEntry"]:
        """Per-user (size_bytes, updated_at) — single-round-trip aggregation.

        Replaces ``list_user_ids()`` + N ``read_memory(uid)`` on dashboard /
        Studio listings.
        """
        return await self._repo.list_memory_summaries()

    def evict_user(self, user_id: str) -> None:
        """Drop the in-memory mirror for one user (test helper / tools)."""
        self._memory.pop(user_id, None)

    async def maybe_consolidate(self, user_id: str) -> None:
        """Run a memory consolidation pass if conditions are met.

        No-op when dreaming is disabled (``config.enable_dream=False``) or
        when the dreamer's gate decides not enough has changed since the
        last pass. Gate logic, retry resilience, and concurrency control
        all live inside the dreamer — callers (typically the runner at
        end-of-turn) just call this once per turn.
        """
        if self._dreamer is None:
            return
        await self._dreamer.maybe_run(user_id)


def build_memory_manager(
    memory_dir: str | Path | None = None,
    *,
    enable_dream: bool = False,
    session_manager: "SessionManager | None" = None,
    llm_factory: "Callable[[], BaseChatModel] | None" = None,
    dream_min_hours: float = 24.0,
    dream_min_sessions: int = 3,
) -> MemoryManager:
    """Factory: builds a ``MemoryManager`` whose backend is picked by
    ``DB_TYPE``.

    ``memory_dir`` is required for the file backend; the SQLite backend
    treats it as a logical workspace label (used by adjacent modules
    like the proactive scanner). The directory itself is created lazily
    by ``FileMemoryRepository`` only when file mode is active.

    When ``enable_dream=True``, ``session_manager`` and ``llm_factory`` are
    required so the manager can construct an internal ``MemoryDreamer``.
    """
    if memory_dir is None:
        memory_dir = Path(tempfile.gettempdir()) / "ark_memory"
    memory_dir = Path(memory_dir)

    from ..storage.factory import build_memory_repository

    repo = build_memory_repository(workspace_dir=memory_dir)
    return MemoryManager(
        repository=repo,
        config=MemoryConfig(
            workspace_dir=str(memory_dir),
            enable_dream=enable_dream,
            dream_min_hours=dream_min_hours,
            dream_min_sessions=dream_min_sessions,
        ),
        session_manager=session_manager,
        llm_factory=llm_factory,
    )
