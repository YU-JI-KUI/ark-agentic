"""Dream system — periodic memory distillation.

Lifecycle role: bridge between Session JSONL (raw) and MEMORY.md (distilled).
Reads recent sessions + current memory → single LLM call → optimistic merge rewrite.

Conservative by default: when in doubt, keep the information.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from pydantic import BaseModel

from .extractor import parse_llm_json
from .user_profile import format_heading_sections, parse_heading_sections

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from ..types import AgentMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dream prompt
# ---------------------------------------------------------------------------

_DREAM_PROMPT = """\
你是一个记忆整理专家。今天是 {current_date}。

## 任务
审阅以下用户记忆文件和最近对话摘要，执行：

1. **合并**语义相近的标题（如"贷款策略"和"保单贷款策略"合并为一个，保留最新内容）
2. **删除**过时信息（被后续记忆或对话明确否定的；仅删除有明确矛盾的，不确定时保留）
3. **保留**所有仍然有效的偏好和决策
4. **提取新信息**：从最近对话中提取值得长期记住的新信息（身份、偏好、决策）
5. **提取潜在需求**：从用户行为模式中推断未被明确表达的需求（标记为 ## 潜在需求）

## 当前记忆文件（约 {token_count} tokens）
{memory_content}

## 最近对话摘要
{session_summaries}

## 容量约束
目标上限 2000 tokens。如果当前超出，请更积极地合并精简。
优先级：身份信息 > 活跃偏好 > 近期决策 > 历史决策。

## 重要原则
- 保守操作：宁可保留冗余信息，也不要删除可能有用的内容
- 合并时保留最新、最具体的描述
- 潜在需求必须有行为模式支撑，不能凭空推断
- 输出格式同输入：heading-based markdown（## 标题 + 内容）

输出严格 JSON（不要包含 markdown 代码块标记）:
{{"distilled": "整理后的完整记忆（heading-based markdown）", "changes": "简述你做了哪些合并/删除/提取"}}
如果不需要任何修改且无新信息，输出 {{"distilled": "", "changes": "无需修改"}}
"""


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


def read_recent_sessions(
    user_id: str,
    sessions_dir: Path,
    since_ts: float,
    token_budget: int = 6000,
) -> str:
    """Read recent session JSONL files and return user+assistant text.

    Uses existing SessionStore + TranscriptManager — no raw JSONL parsing.
    """
    from ..compaction import estimate_tokens
    from ..persistence import SessionStore, TranscriptManager

    store = SessionStore(sessions_dir)
    transcript = TranscriptManager(sessions_dir)

    entries = store.load(user_id)
    recent = sorted(
        [e for e in entries.values() if e.updated_at / 1000 > since_ts],
        key=lambda e: e.updated_at,
        reverse=True,
    )

    texts: list[str] = []
    total_tokens = 0
    for entry in recent:
        try:
            messages = transcript.load_messages(entry.session_id, user_id)
        except Exception:
            logger.debug("Failed to load session %s, skipping", entry.session_id)
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


def should_dream(
    user_id: str,
    workspace_dir: Path,
    sessions_dir: Path,
    min_hours: float = 24.0,
    min_sessions: int = 3,
) -> bool:
    """Check if a dream cycle should run for this user."""
    last_dream_file = workspace_dir / user_id / ".last_dream"
    if not last_dream_file.exists():
        touch_last_dream(user_id, workspace_dir)
        return False

    try:
        last_ts = float(last_dream_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        touch_last_dream(user_id, workspace_dir)
        return False

    hours_since = (time.time() - last_ts) / 3600
    if hours_since < min_hours:
        return False

    from ..persistence import SessionStore

    store = SessionStore(sessions_dir)
    entries = store.load(user_id)
    recent = [e for e in entries.values() if e.updated_at / 1000 > last_ts]
    return len(recent) >= min_sessions


def touch_last_dream(user_id: str, workspace_dir: Path) -> None:
    """Write current timestamp to .last_dream file."""
    p = workspace_dir / user_id / ".last_dream"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(time.time()), encoding="utf-8")


# ---------------------------------------------------------------------------
# Dreamer
# ---------------------------------------------------------------------------


class MemoryDreamer:
    """Periodic memory distillation via LLM."""

    def __init__(self, llm_factory: Callable[[], "BaseChatModel"]) -> None:
        self._get_llm = llm_factory

    async def dream(
        self,
        memory_content: str,
        session_summaries: str = "",
    ) -> DreamResult:
        """Run LLM distillation on memory + recent session context."""
        if not memory_content.strip() and not session_summaries.strip():
            return DreamResult(changes="Empty memory and no sessions, nothing to distill")

        from ..compaction import estimate_tokens

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
        memory_path: Path,
        result: DreamResult,
        original_snapshot: str,
    ) -> None:
        """Write distilled content with optimistic merge.

        Preserves any headings added by concurrent memory_write during
        the dream window.
        """
        if not result.has_changes:
            logger.info("Dream: no changes to apply for %s", memory_path)
            return

        # 1. Backup (resilient to disk-full)
        try:
            if memory_path.exists():
                bak = memory_path.with_suffix(".md.bak")
                bak.write_text(
                    memory_path.read_text(encoding="utf-8"), encoding="utf-8"
                )
        except OSError:
            logger.warning("Failed to write .bak for %s, proceeding anyway", memory_path)

        # 2. Re-read current state (may have changed during dream)
        current = ""
        if memory_path.exists():
            current = memory_path.read_text(encoding="utf-8")
        current_preamble, current_sections = parse_heading_sections(current)
        _, original_sections = parse_heading_sections(original_snapshot)
        _, distilled_sections = parse_heading_sections(result.distilled)

        if not distilled_sections:
            logger.warning("Dream produced empty sections, skipping write")
            return

        # 3. Detect headings added AFTER dream started (concurrent memory_write)
        new_during_dream = {
            k: v
            for k, v in current_sections.items()
            if k not in original_sections
        }

        # 4. Merge: distilled base + preserve concurrent writes
        final = {**distilled_sections, **new_during_dream}

        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text(
            format_heading_sections(current_preamble, final), encoding="utf-8"
        )
        logger.info("Dream applied to %s: %s", memory_path, result.changes)

    async def run(
        self,
        memory_path: Path,
        sessions_dir: Path,
        user_id: str,
    ) -> DreamResult:
        """Full dream cycle: read sessions + memory → distill → optimistic merge write."""
        memory_content = ""
        if memory_path.exists():
            memory_content = memory_path.read_text(encoding="utf-8")
        original_snapshot = memory_content

        # Read .last_dream timestamp to know how far back to look
        last_dream_file = memory_path.parent / ".last_dream"
        since_ts = 0.0
        if last_dream_file.exists():
            try:
                since_ts = float(last_dream_file.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pass

        session_summaries = read_recent_sessions(
            user_id, sessions_dir, since_ts,
        )

        result = await self.dream(memory_content, session_summaries)

        if result.has_changes:
            await self.apply(memory_path, result, original_snapshot)

        # Update last dream timestamp
        touch_last_dream(user_id, memory_path.parent.parent)

        return result
