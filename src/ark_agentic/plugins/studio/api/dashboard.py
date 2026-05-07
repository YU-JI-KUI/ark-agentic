"""Studio Dashboard summary — single aggregate endpoint (BFF / API Composition).

Replaces the dashboard's previous 4N fan-out (skills + tools + sessions +
memory per agent) with a single response that the frontend renders directly.
The handler is wrapped by a 2-second in-process TTL cache + an ETag so a
freshly-loaded dashboard reuses the cached payload across users while still
revalidating after writes settle. No Redis / no fastapi-cache.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from ark_agentic.core.runtime.registry import AgentRegistry
from ark_agentic.core.storage.entries import MemorySummaryEntry
from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.plugins.studio.services import skill_service, tool_service
from ark_agentic.plugins.studio.services.auth import require_studio_user

from ._deps import get_registry
from .agents import _read_agent_meta

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_studio_user)])

_TREND_MONTH_COUNT = 6
_DISTRIBUTION_LIMIT = 6
_ACTIVITY_LIMIT = 12


# ── Response models (match frontend DashboardSummary) ───────────────


class TrendPoint(BaseModel):
    label: str
    short_label: str
    value: int


class DistributionItem(BaseModel):
    label: str
    value: int
    hint: str | None = None


class InsightStat(BaseModel):
    label: str
    value: str
    hint: str | None = None


class SkillsSection(BaseModel):
    stats: list[InsightStat]
    groups: list[DistributionItem]
    tags: list[DistributionItem]


class ToolsSection(BaseModel):
    stats: list[InsightStat]
    groups: list[DistributionItem]
    agents: list[DistributionItem]


class SessionsSection(BaseModel):
    stats: list[InsightStat]
    agents: list[DistributionItem]
    message_bands: list[DistributionItem]


class MemorySection(BaseModel):
    stats: list[InsightStat]
    file_types: list[DistributionItem]
    agents: list[DistributionItem]


class ActivityItem(BaseModel):
    ts: str
    kind: str  # 'skill' | 'tool' | 'session' | 'memory'
    agent: str
    agent_label: str
    text: str
    status: str  # 'ok' | 'warn' | 'error'


class TrendsSection(BaseModel):
    users: list[TrendPoint]
    skills: list[TrendPoint]
    tools: list[TrendPoint]
    sessions: list[TrendPoint]
    memory: list[TrendPoint]


class DashboardSummary(BaseModel):
    total_agents: int
    total_users: int
    total_skills: int
    total_tools: int
    total_sessions: int
    total_memory_files: int
    total_memory_bytes: int
    trends: TrendsSection
    skills: SkillsSection
    tools: ToolsSection
    sessions: SessionsSection
    memory: MemorySection
    activity: list[ActivityItem]
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


# ── Aggregation helpers ─────────────────────────────────────────────


def _format_ratio(part: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{round((part / total) * 100)}%"


def _format_compact(value: int) -> str:
    """Locale-neutral grouped formatting (e.g. ``12,345``).

    Latin "K/M" abbreviations are not locale-aware (zh-CN expects
    ``万`` / ``亿`` instead). Top-level totals on the dashboard are
    formatted client-side via ``Intl.NumberFormat``; the strings this
    helper produces are only used inside ``InsightStat`` and
    ``DistributionItem`` hints, where digit grouping reads cleanly in
    every locale.
    """
    return f"{value:,}"


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _month_buckets(count: int) -> list[tuple[str, str, int]]:
    """Return (label, short_label, end_epoch_ms) for the trailing N months."""
    now = datetime.now(timezone.utc)
    buckets: list[tuple[str, str, int]] = []
    for i in range(count):
        offset = count - 1 - i
        year = now.year
        month = now.month - offset
        while month <= 0:
            month += 12
            year -= 1
        # End of month
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1
        end_dt = datetime(next_year, next_month, 1, tzinfo=timezone.utc)
        end_ms = int(end_dt.timestamp() * 1000) - 1
        label = f"{year}-{month:02d}"
        short = f"{month:02d}"
        buckets.append((label, short, end_ms))
    return buckets


def _build_cumulative_trend(timestamps_ms: list[int]) -> list[TrendPoint]:
    buckets = _month_buckets(_TREND_MONTH_COUNT)
    sorted_ts = sorted(timestamps_ms)
    cursor = 0
    points: list[TrendPoint] = []
    for label, short, end_ms in buckets:
        while cursor < len(sorted_ts) and sorted_ts[cursor] <= end_ms:
            cursor += 1
        points.append(TrendPoint(label=label, short_label=short, value=cursor))
    return points


def _sort_distribution(
    counts: dict[str, int],
    total: int,
    limit: int = _DISTRIBUTION_LIMIT,
) -> list[DistributionItem]:
    items = [
        DistributionItem(
            label=label, value=value, hint=_format_ratio(value, total),
        )
        for label, value in counts.items()
        if value > 0
    ]
    items.sort(key=lambda i: (-i.value, i.label))
    return items[:limit]


def _parse_iso_to_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


# ── Per-section builders ────────────────────────────────────────────


def _agent_label(meta: Any) -> str:
    return meta.name or meta.id


async def _collect_agents() -> list[Any]:
    """Resolve dashboard's view of agents from agents.json on disk.

    Uses the same source as ``GET /api/studio/agents`` so the dashboard
    counts match the listing exactly even when the registry hasn't
    discovered every directory yet (e.g. a freshly added agent).
    """
    agents_root = get_agents_root()
    metas: list[Any] = []
    if not agents_root.is_dir():
        return metas
    for child in sorted(agents_root.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        meta = _read_agent_meta(child)
        if meta is None:
            from .agents import AgentMeta as _AgentMeta
            meta = _AgentMeta(id=child.name, name=child.name)
        metas.append(meta)
    return metas


def _collect_skills(agents_root: Path, agents: list[Any]) -> list[tuple[Any, Any]]:
    pairs: list[tuple[Any, Any]] = []
    for agent in agents:
        try:
            for skill in skill_service.list_skills(agents_root, agent.id):
                pairs.append((agent, skill))
        except FileNotFoundError:
            continue
    return pairs


def _collect_tools(agents_root: Path, agents: list[Any]) -> list[tuple[Any, Any]]:
    pairs: list[tuple[Any, Any]] = []
    for agent in agents:
        try:
            for tool in tool_service.list_tools(agents_root, agent.id):
                pairs.append((agent, tool))
        except FileNotFoundError:
            continue
    return pairs


async def _collect_sessions(
    registry: AgentRegistry, agents: list[Any],
) -> list[tuple[Any, Any]]:
    """Return (agent_meta, SessionSummaryEntry) pairs across registered agents."""
    pairs: list[tuple[Any, Any]] = []
    for agent in agents:
        try:
            runner = registry.get(agent.id)
        except KeyError:
            continue
        for summary in await runner.session_manager.list_session_summaries():
            pairs.append((agent, summary))
    return pairs


async def _collect_memory(
    registry: AgentRegistry, agents: list[Any],
) -> list[tuple[Any, Any]]:
    """Collect (agent, MemorySummaryEntry) pairs across registered agents.

    Combines two sources to mirror Studio's per-agent memory listing:

    - ``mm.list_memory_summaries()`` — per-user ``{user}/MEMORY.md``
      rows from the active memory backend (file or DB).
    - Workspace scan — global ``MEMORY.md`` and ``memory/*.md`` files
      that live alongside the user dirs but have no DB representation.
      Without this scan the dashboard's memory totals would miss every
      non-user-scoped memory file (regression vs the previous client-
      side aggregator).
    """
    pairs: list[tuple[Any, Any]] = []
    for agent in agents:
        try:
            runner = registry.get(agent.id)
        except KeyError:
            continue
        mm = runner.memory_manager
        if mm is None:
            continue
        for summary in await mm.list_memory_summaries():
            pairs.append((agent, summary))
        workspace_dir = Path(getattr(mm.config, "workspace_dir", "") or "")
        if workspace_dir.is_dir():
            for entry in _scan_workspace_memory(workspace_dir):
                pairs.append((agent, entry))
    return pairs


def _scan_workspace_memory(workspace: Path) -> list[MemorySummaryEntry]:
    """Pick up workspace-level MEMORY.md + knowledge/*.md.

    Mirrors ``studio.api.memory._scan_memory_files`` for the categories
    that have no per-user repository row.
    """
    rows: list[MemorySummaryEntry] = []
    global_md = workspace / "MEMORY.md"
    if global_md.is_file():
        st = global_md.stat()
        rows.append(MemorySummaryEntry(
            user_id="",
            size_bytes=st.st_size,
            updated_at=int(st.st_mtime * 1000),
            file_type="memory",
            path="MEMORY.md",
        ))
    knowledge_dir = workspace / "memory"
    if knowledge_dir.is_dir():
        for md in sorted(knowledge_dir.glob("*.md")):
            if not md.is_file():
                continue
            st = md.stat()
            rows.append(MemorySummaryEntry(
                user_id="",
                size_bytes=st.st_size,
                updated_at=int(st.st_mtime * 1000),
                file_type="knowledge",
                path=f"memory/{md.name}",
            ))
    return rows


def _build_skills_section(
    skill_pairs: list[tuple[Any, Any]], agents: list[Any],
) -> SkillsSection:
    total = len(skill_pairs)
    agents_with = len({a.id for a, _ in skill_pairs})
    grouped = sum(1 for _, s in skill_pairs if (s.group or "").strip())
    tagged = sum(
        1 for _, s in skill_pairs
        if any((tag or "").strip() for tag in (s.tags or []))
    )
    group_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    for _, s in skill_pairs:
        group_counts[(s.group or "").strip() or "ungrouped"] = (
            group_counts.get((s.group or "").strip() or "ungrouped", 0) + 1
        )
        tags = [t.strip() for t in (s.tags or []) if t and t.strip()]
        if not tags:
            tag_counts["untagged"] = tag_counts.get("untagged", 0) + 1
        else:
            for t in tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1

    return SkillsSection(
        stats=[
            InsightStat(
                label="Agents Covered",
                value=f"{agents_with}/{len(agents)}",
                hint=_format_ratio(agents_with, len(agents)),
            ),
            InsightStat(
                label="Grouped Skills",
                value=f"{grouped}/{total}",
                hint=_format_ratio(grouped, total),
            ),
            InsightStat(
                label="Tagged Skills",
                value=f"{tagged}/{total}",
                hint=_format_ratio(tagged, total),
            ),
        ],
        groups=_sort_distribution(group_counts, total),
        tags=_sort_distribution(tag_counts, total),
    )


def _build_tools_section(
    tool_pairs: list[tuple[Any, Any]], agents: list[Any],
) -> ToolsSection:
    total = len(tool_pairs)
    agents_with = len({a.id for a, _ in tool_pairs})
    documented = sum(1 for _, t in tool_pairs if (t.description or "").strip())
    typed = sum(1 for _, t in tool_pairs if t.parameters)
    group_counts: dict[str, int] = {}
    by_agent: dict[str, tuple[str, int]] = {}
    for a, t in tool_pairs:
        key = (t.group or "").strip() or "ungrouped"
        group_counts[key] = group_counts.get(key, 0) + 1
        label = _agent_label(a)
        prev = by_agent.get(a.id)
        by_agent[a.id] = (label, (prev[1] if prev else 0) + 1)

    agent_items = [
        DistributionItem(label=label, value=count, hint=agent_id)
        for agent_id, (label, count) in by_agent.items()
        if count > 0
    ]
    agent_items.sort(key=lambda i: (-i.value, i.label))
    return ToolsSection(
        stats=[
            InsightStat(
                label="Agents Covered",
                value=f"{agents_with}/{len(agents)}",
                hint=_format_ratio(agents_with, len(agents)),
            ),
            InsightStat(
                label="Documented",
                value=f"{documented}/{total}",
                hint=_format_ratio(documented, total),
            ),
            InsightStat(
                label="Schema Ready",
                value=f"{typed}/{total}",
                hint=_format_ratio(typed, total),
            ),
        ],
        groups=_sort_distribution(group_counts, total),
        agents=agent_items[:_DISTRIBUTION_LIMIT],
    )


def _build_sessions_section(
    session_pairs: list[tuple[Any, Any]], agents: list[Any],
) -> SessionsSection:
    total = len(session_pairs)
    agents_with = len({a.id for a, _ in session_pairs})
    distinct_users = {
        (s.user_id or "").strip()
        for _, s in session_pairs
        if (s.user_id or "").strip()
    }
    non_empty = sum(1 for _, s in session_pairs if s.message_count > 0)
    total_messages = sum(s.message_count for _, s in session_pairs)
    bands: dict[str, int] = {
        "0 messages": 0,
        "1-5 messages": 0,
        "6-20 messages": 0,
        "21+ messages": 0,
    }
    by_agent: dict[str, tuple[str, int, int]] = {}
    for a, s in session_pairs:
        if s.message_count <= 0:
            bands["0 messages"] += 1
        elif s.message_count <= 5:
            bands["1-5 messages"] += 1
        elif s.message_count <= 20:
            bands["6-20 messages"] += 1
        else:
            bands["21+ messages"] += 1
        label = _agent_label(a)
        prev = by_agent.get(a.id)
        prev_count = prev[1] if prev else 0
        prev_msgs = prev[2] if prev else 0
        by_agent[a.id] = (label, prev_count + 1, prev_msgs + s.message_count)

    agent_items = [
        DistributionItem(
            label=label, value=count,
            hint=f"{_format_compact(msgs)} msgs" if count > 0 else "no sessions",
        )
        for _, (label, count, msgs) in by_agent.items()
        if count > 0
    ]
    agent_items.sort(key=lambda i: (-i.value, i.label))
    avg = f"{total_messages / total:.1f}" if total > 0 else "0"

    return SessionsSection(
        stats=[
            InsightStat(
                label="Agents Covered",
                value=f"{agents_with}/{len(agents)}",
                hint=_format_ratio(agents_with, len(agents)),
            ),
            InsightStat(
                label="Users Covered",
                value=_format_compact(len(distinct_users)),
                hint="distinct users",
            ),
            InsightStat(
                label="Non-empty Sessions",
                value=f"{non_empty}/{total}",
                hint=_format_ratio(non_empty, total),
            ),
            InsightStat(
                label="Avg Msg / Session",
                value=avg,
                hint=f"{_format_compact(total_messages)} messages",
            ),
        ],
        agents=agent_items[:_DISTRIBUTION_LIMIT],
        message_bands=[
            DistributionItem(
                label=label, value=value, hint=_format_ratio(value, total),
            )
            for label, value in bands.items()
        ],
    )


def _build_memory_section(
    memory_pairs: list[tuple[Any, Any]], agents: list[Any],
) -> MemorySection:
    total_files = len(memory_pairs)
    total_bytes = sum(s.size_bytes for _, s in memory_pairs)
    agents_with = len({a.id for a, _ in memory_pairs})
    distinct_users = {
        (s.user_id or "").strip()
        for _, s in memory_pairs
        if (s.user_id or "").strip()
    }
    file_types: dict[str, int] = {}
    by_agent: dict[str, tuple[str, int, int]] = {}
    for a, s in memory_pairs:
        kind = (s.file_type or "memory").strip() or "memory"
        file_types[kind] = file_types.get(kind, 0) + 1
        label = _agent_label(a)
        prev = by_agent.get(a.id)
        by_agent[a.id] = (
            label,
            (prev[1] if prev else 0) + 1,
            (prev[2] if prev else 0) + s.size_bytes,
        )

    agent_items = [
        DistributionItem(
            label=label, value=size,
            hint=f"{_format_compact(count)} files",
        )
        for _, (label, count, size) in by_agent.items()
        if size > 0
    ]
    agent_items.sort(key=lambda i: (-i.value, i.label))

    return MemorySection(
        stats=[
            InsightStat(
                label="Agents Covered",
                value=f"{agents_with}/{len(agents)}",
                hint=_format_ratio(agents_with, len(agents)),
            ),
            InsightStat(
                label="Users Covered",
                value=_format_compact(len(distinct_users)),
                hint="memory users",
            ),
            InsightStat(
                label="Storage",
                value=_format_bytes(total_bytes),
                hint=f"{_format_compact(total_files)} files",
            ),
            InsightStat(
                label="File Types",
                value=_format_compact(len(file_types)),
                hint="distinct types",
            ),
        ],
        file_types=_sort_distribution(file_types, total_files),
        agents=agent_items[:_DISTRIBUTION_LIMIT],
    )


def _build_trends(
    skill_pairs: list[tuple[Any, Any]],
    tool_pairs: list[tuple[Any, Any]],
    session_pairs: list[tuple[Any, Any]],
    memory_pairs: list[tuple[Any, Any]],
) -> TrendsSection:
    user_first_seen: dict[str, int] = {}

    def _track(uid: str | None, ms: int | None) -> None:
        if not uid or not uid.strip() or ms is None:
            return
        prev = user_first_seen.get(uid)
        if prev is None or ms < prev:
            user_first_seen[uid] = ms

    skill_ts = [
        _parse_iso_to_ms(s.modified_at) or _parse_iso_to_ms(a.updated_at)
        for a, s in skill_pairs
    ]
    tool_ts = [
        _parse_iso_to_ms(t.modified_at) or _parse_iso_to_ms(a.updated_at)
        for a, t in tool_pairs
    ]
    session_ts = [s.updated_at for _, s in session_pairs if s.updated_at]
    memory_ts = [s.updated_at for _, s in memory_pairs if s.updated_at]

    for _, s in session_pairs:
        _track(s.user_id, s.updated_at)
    for _, s in memory_pairs:
        _track(s.user_id, s.updated_at)

    return TrendsSection(
        users=_build_cumulative_trend(list(user_first_seen.values())),
        skills=_build_cumulative_trend([t for t in skill_ts if t is not None]),
        tools=_build_cumulative_trend([t for t in tool_ts if t is not None]),
        sessions=_build_cumulative_trend(session_ts),
        memory=_build_cumulative_trend(memory_ts),
    )


def _build_activity(
    skill_pairs: list[tuple[Any, Any]],
    tool_pairs: list[tuple[Any, Any]],
    session_pairs: list[tuple[Any, Any]],
    memory_pairs: list[tuple[Any, Any]],
) -> list[ActivityItem]:
    items: list[tuple[int, ActivityItem]] = []

    def _ts_to_iso(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()

    for a, skill in skill_pairs:
        ms = _parse_iso_to_ms(skill.modified_at)
        if ms is None:
            continue
        items.append((ms, ActivityItem(
            ts=_ts_to_iso(ms), kind="skill", agent=a.id,
            agent_label=_agent_label(a),
            text=f"Skill {skill.name} updated", status="ok",
        )))
    for a, tool in tool_pairs:
        ms = _parse_iso_to_ms(tool.modified_at)
        if ms is None:
            continue
        items.append((ms, ActivityItem(
            ts=_ts_to_iso(ms), kind="tool", agent=a.id,
            agent_label=_agent_label(a),
            text=f"Tool {tool.name} updated", status="ok",
        )))
    for a, s in session_pairs:
        if not s.updated_at:
            continue
        items.append((s.updated_at, ActivityItem(
            ts=_ts_to_iso(s.updated_at), kind="session", agent=a.id,
            agent_label=_agent_label(a),
            text=f"Session {s.session_id[:8]} ({s.message_count} msgs)",
            status="warn" if s.message_count == 0 else "ok",
        )))
    for a, s in memory_pairs:
        if not s.updated_at:
            continue
        path = s.path or (
            f"{s.user_id}/MEMORY.md" if s.user_id else "MEMORY.md"
        )
        items.append((s.updated_at, ActivityItem(
            ts=_ts_to_iso(s.updated_at), kind="memory", agent=a.id,
            agent_label=_agent_label(a),
            text=f"Memory {path} updated", status="ok",
        )))

    items.sort(key=lambda t: t[0], reverse=True)
    return [item for _, item in items[:_ACTIVITY_LIMIT]]


# ── Builder ─────────────────────────────────────────────────────────


async def _build_summary(registry: AgentRegistry) -> DashboardSummary:
    agents = await _collect_agents()
    agents_root = get_agents_root()
    skill_pairs = _collect_skills(agents_root, agents)
    tool_pairs = _collect_tools(agents_root, agents)
    session_pairs = await _collect_sessions(registry, agents)
    memory_pairs = await _collect_memory(registry, agents)

    distinct_users: set[str] = set()
    for _, s in session_pairs:
        if (s.user_id or "").strip():
            distinct_users.add(s.user_id.strip())
    for _, s in memory_pairs:
        if (s.user_id or "").strip():
            distinct_users.add(s.user_id.strip())

    return DashboardSummary(
        total_agents=len(agents),
        total_users=len(distinct_users),
        total_skills=len(skill_pairs),
        total_tools=len(tool_pairs),
        total_sessions=len(session_pairs),
        total_memory_files=len(memory_pairs),
        total_memory_bytes=sum(s.size_bytes for _, s in memory_pairs),
        trends=_build_trends(
            skill_pairs, tool_pairs, session_pairs, memory_pairs,
        ),
        skills=_build_skills_section(skill_pairs, agents),
        tools=_build_tools_section(tool_pairs, agents),
        sessions=_build_sessions_section(session_pairs, agents),
        memory=_build_memory_section(memory_pairs, agents),
        activity=_build_activity(
            skill_pairs, tool_pairs, session_pairs, memory_pairs,
        ),
    )


# ── Endpoint ────────────────────────────────────────────────────────


@router.get(
    "/dashboard/summary",
    response_model=DashboardSummary,
    response_model_exclude_none=False,
)
async def get_dashboard_summary(
    response: Response,
    registry: AgentRegistry = Depends(get_registry),
):
    summary = await _build_summary(registry)
    response.headers["Cache-Control"] = "max-age=2"
    return summary
