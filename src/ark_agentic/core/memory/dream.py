"""Dream system — periodic memory distillation.

Lifecycle role: bridge between Session JSONL (raw) and MEMORY.md (distilled).
Reads recent sessions + current memory → single LLM call → optimistic merge.

``MemoryDreamer`` is fully self-contained: callers only ever call
``maybe_run(user_id)``. Gate logic, run, and retry resilience all live here
so the runner does not depend on any storage protocol for dreaming.

Conservative by default: when in doubt, keep the information.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from pydantic import BaseModel

from .extractor import parse_llm_json
from .rules import MEMORY_FILTER_RULES
from .user_profile import format_heading_sections, parse_heading_sections

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from ..session import SessionManager
    from ..storage.protocols import MemoryRepository
    from ..types import AgentMessage
    from .manager import MemoryManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dream prompt
# ---------------------------------------------------------------------------

_DREAM_PROMPT = """\
你是一个记忆整理专家。今天是 {{current_date}}。

## 任务
审阅以下用户记忆文件和最近对话摘要，执行：

1. **合并**语义相近的标题（如"贷款策略"和"保单贷款策略"合并为一个，保留最新内容）
2. **删除**过时信息（被后续记忆或对话明确否定的；仅删除有明确矛盾的，不确定时保留）
3. **保留**所有仍然有效的偏好
4. **提取新信息**：从最近对话中提取值得长期记住的新信息，严格遵守下方记录规则

{filter_rules}

## 当前记忆文件（约 {{token_count}} tokens）
{{memory_content}}

## 最近对话摘要
{{session_summaries}}

## 容量约束
目标上限 2000 tokens。如果当前超出，请更积极地合并精简。
优先级：身份信息 > 活跃偏好 > 持久业务偏好 > 风险偏好。

## 重要原则
- 保守操作：宁可保留冗余信息，也不要删除可能有用的内容
- 合并时保留最新、最具体的描述
- 输出格式同输入：heading-based markdown（## 标题 + 内容）

输出严格 JSON（不要包含 markdown 代码块标记）:
{{{{"distilled": "整理后的完整记忆（heading-based markdown）", "changes": "简述你做了哪些合并/删除/提取"}}}}
如果不需要任何修改且无新信息，输出 {{{{"distilled": "", "changes": "无需修改"}}}}
""".format(filter_rules=MEMORY_FILTER_RULES)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class DreamResult(BaseModel):
    distilled: str = ""
    changes: str = ""

    @property
    def has_changes(self) -> bool:
        return bool(self.distilled.strip())


# ---------------------------------------------------------------------------
# Session reader
# ---------------------------------------------------------------------------


def format_session_for_dream(messages: list["AgentMessage"]) -> str:
    """Extract user + assistant text, skip system/tool noise."""
    from ..types import MessageRole

    lines: list[str] = []
    for m in messages:
        if m.role in (MessageRole.USER, MessageRole.ASSISTANT) and m.content:
            lines.append(f"{m.role.value}: {m.content}")
    return "\n".join(lines)


async def read_recent_sessions(
    user_id: str,
    session_manager: "SessionManager",
    since_ts: float,
    token_budget: int = 6000,
) -> str:
    """Return user+assistant text from sessions updated after ``since_ts``.

    Reads through ``SessionManager``'s narrow public methods so dreaming
    stays one layer above storage — memory subsystem doesn't know whether
    sessions live in files or SQLite.
    """
    from ..session.compaction import estimate_tokens

    metas = await session_manager.list_user_session_metas(user_id)
    recent = [m for m in metas if m.updated_at / 1000 > since_ts]

    texts: list[str] = []
    total_tokens = 0
    for entry in recent:
        try:
            messages = await session_manager.load_session_messages(
                entry.session_id, user_id,
            )
        except Exception:
            logger.debug(
                "Failed to load session %s, skipping", entry.session_id,
            )
            continue
        session_text = format_session_for_dream(messages)
        if not session_text:
            continue
        tokens = estimate_tokens(session_text)
        if total_tokens + tokens > token_budget:
            break
        texts.append(session_text)
        total_tokens += tokens

    return "\n---\n".join(texts)


# ---------------------------------------------------------------------------
# Dream gate
# ---------------------------------------------------------------------------


async def should_dream(
    memory_repo: "MemoryRepository",
    session_manager: "SessionManager",
    user_id: str,
    min_hours: float = 24.0,
    min_sessions: int = 3,
) -> bool:
    """Check if a dream cycle should run for this user.

    Reads ``last_dream_at`` from the memory repository and counts
    recently-updated sessions via the SessionManager.
    """
    last_ts = await memory_repo.get_last_dream_at(user_id)
    if last_ts is None:
        # First observation: seed the marker so future calls measure from now.
        await memory_repo.set_last_dream_at(user_id, time.time())
        return False

    hours_since = (time.time() - last_ts) / 3600
    if hours_since >= min_hours:
        return True

    metas = await session_manager.list_user_session_metas(user_id)
    recent = [m for m in metas if m.updated_at / 1000 > last_ts]
    return len(recent) >= min_sessions


# ---------------------------------------------------------------------------
# Dreamer
# ---------------------------------------------------------------------------


class MemoryDreamer:
    """Periodic memory distillation via LLM.

    Owns all of its dependencies; callers only need to call
    ``maybe_run(user_id)``. The gate (``should_dream``), the run, and the
    failure-counter resilience all live inside the class.
    """

    _FAILURE_THRESHOLD = 3

    def __init__(
        self,
        llm_factory: Callable[[], "BaseChatModel"],
        memory_manager: "MemoryManager | None" = None,
        session_manager: "SessionManager | None" = None,
        memory_repo: "MemoryRepository | None" = None,
        *,
        min_sessions: int = 3,
        min_hours: float = 24.0,
    ) -> None:
        """Storage deps are optional for tests that only exercise ``dream`` /
        ``apply`` / ``_parse_response``; ``run`` and ``maybe_run`` require
        all three and raise ``RuntimeError`` if missing."""
        self._get_llm = llm_factory
        self._memory_manager = memory_manager
        self._session_manager = session_manager
        self._memory_repo = memory_repo
        self._min_sessions = min_sessions
        self._min_hours = min_hours

        self._tasks: dict[str, asyncio.Task] = {}
        self._failures: dict[str, int] = {}

    def _require_storage(self) -> tuple["MemoryManager", "SessionManager", "MemoryRepository"]:
        if (
            self._memory_manager is None
            or self._session_manager is None
            or self._memory_repo is None
        ):
            raise RuntimeError(
                "MemoryDreamer.run / maybe_run require memory_manager, "
                "session_manager, and memory_repo to be supplied at construction."
            )
        return self._memory_manager, self._session_manager, self._memory_repo

    async def dream(
        self,
        memory_content: str,
        session_summaries: str = "",
    ) -> DreamResult:
        """Run LLM distillation on memory + recent session context."""
        if not memory_content.strip() and not session_summaries.strip():
            return DreamResult(changes="Empty memory and no sessions, nothing to distill")

        from ..session.compaction import estimate_tokens

        prompt = _DREAM_PROMPT.format(
            current_date=datetime.now().isoformat()[:10],
            token_count=estimate_tokens(memory_content) if memory_content else 0,
            memory_content=memory_content or "(empty)",
            session_summaries=session_summaries or "(no recent sessions)",
        )
        llm = self._get_llm()
        response = await llm.ainvoke(prompt)

        raw = response.content
        if isinstance(raw, list):
            raw = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in raw
            )

        return self._parse_response(str(raw))

    def _parse_response(self, raw: str) -> DreamResult:
        data = parse_llm_json(raw)
        if not data:
            if raw and raw.strip():
                logger.warning("Dream returned non-JSON: %.100s", raw.strip())
            return DreamResult()

        return DreamResult(
            distilled=str(data.get("distilled", "")).strip(),
            changes=str(data.get("changes", "")).strip(),
        )

    async def apply(
        self,
        memory_manager: "MemoryManager",
        user_id: str,
        result: DreamResult,
        original_snapshot: str,
    ) -> None:
        """Write distilled content with optimistic merge.

        Preserves any headings added by concurrent memory_write during
        the dream window. Backend-agnostic — atomic write guaranteed by
        ``MemoryManager.overwrite`` (file: tmp+rename; SQLite: txn).
        """
        if not result.has_changes:
            logger.info("Dream: no changes to apply for user %s", user_id)
            return

        # Re-read current state (may have changed during dream)
        current = await memory_manager.read_memory(user_id)
        current_preamble, current_sections = parse_heading_sections(current)
        _, original_sections = parse_heading_sections(original_snapshot)
        _, distilled_sections = parse_heading_sections(result.distilled)

        if not distilled_sections:
            logger.warning("Dream produced empty sections, skipping write")
            return

        # Detect headings added AFTER dream started (concurrent memory_write)
        new_during_dream = {
            k: v
            for k, v in current_sections.items()
            if k not in original_sections
        }

        # Merge: distilled base + preserve concurrent writes
        final = {**distilled_sections, **new_during_dream}

        await memory_manager.overwrite(
            user_id, format_heading_sections(current_preamble, final)
        )
        logger.info("Dream applied for user %s: %s", user_id, result.changes)

    async def run(self, user_id: str) -> DreamResult:
        """Full dream cycle: read sessions + memory → distill → merge write."""
        memory_manager, session_manager, memory_repo = self._require_storage()

        memory_content = await memory_manager.read_memory(user_id)
        original_snapshot = memory_content

        since_ts = await memory_repo.get_last_dream_at(user_id) or 0.0

        session_summaries = await read_recent_sessions(
            user_id, session_manager, since_ts,
        )

        result = await self.dream(memory_content, session_summaries)

        if result.has_changes:
            await self.apply(
                memory_manager, user_id, result, original_snapshot,
            )

        await memory_repo.set_last_dream_at(user_id, time.time())

        return result

    async def maybe_run(self, user_id: str) -> None:
        """Gate + spawn a background dream task if thresholds are met.

        Returns immediately when:
          - a task for ``user_id`` is already in flight
          - the dream gate is closed (recent dream / not enough sessions)
          - the gate check itself fails

        Resilience: after ``_FAILURE_THRESHOLD`` consecutive failures the
        ``last_dream_at`` marker is advanced anyway so a permanently-broken
        user can't pin the gate open forever.
        """
        _, session_manager, memory_repo = self._require_storage()
        active = self._tasks.get(user_id)
        if active is not None and not active.done():
            return

        try:
            ok = await should_dream(
                memory_repo, session_manager, user_id,
                min_hours=self._min_hours,
                min_sessions=self._min_sessions,
            )
        except Exception:
            logger.debug(
                "Dream gate check failed for %s", user_id, exc_info=True,
            )
            return
        if not ok:
            return

        self._tasks[user_id] = asyncio.create_task(
            self._run_with_retry_protection(user_id)
        )
        logger.info("Dream triggered for user %s", user_id)

    async def _run_with_retry_protection(self, user_id: str) -> None:
        _, _, memory_repo = self._require_storage()
        try:
            result = await self.run(user_id)
            self._failures.pop(user_id, None)
            logger.info(
                "Dream completed for user %s: %s", user_id, result.changes,
            )
        except Exception:
            logger.warning("Dream failed for user %s", user_id, exc_info=True)
            failures = self._failures.get(user_id, 0) + 1
            self._failures[user_id] = failures
            if failures >= self._FAILURE_THRESHOLD:
                await memory_repo.set_last_dream_at(user_id, time.time())
                self._failures.pop(user_id, None)
                logger.warning(
                    "Dream failed %d consecutive times for %s, "
                    "advancing last_dream_at",
                    failures, user_id,
                )
