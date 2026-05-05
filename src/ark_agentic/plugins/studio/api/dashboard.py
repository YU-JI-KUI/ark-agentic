"""Studio Dashboard summary — single aggregate endpoint (BFF / API Composition).

Replaces the dashboard's previous 4N fan-out (skills + tools + sessions +
memory per agent) with a single response that the frontend renders directly.
The handler is wrapped by a 2-second in-process TTL cache + an ETag so a
freshly-loaded dashboard reuses the cached payload across users while still
revalidating after writes settle. No Redis / no fastapi-cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field

from ark_agentic.core.utils.env import get_agents_root
from ark_agentic.plugins.api.deps import get_registry
from ark_agentic.plugins.studio.services import skill_service, tool_service
from ark_agentic.plugins.studio.services.auth import require_studio_user

from .agents import _read_agent_meta

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_studio_user)])

_CACHE_TTL_SECONDS = 2.0
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
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}K".replace(".0K", "K")
    return str(value)


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
    agents_root = get_agents_root(__file__)
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


async def _collect_sessions(agents: list[Any]) -> list[tuple[Any, Any]]:
    """Return (agent_meta, SessionSummaryEntry) pairs across registered agents."""
    registry = get_registry()
    pairs: list[tuple[Any, Any]] = []
    for agent in agents:
        try:
            runner = registry.get(agent.id)
        except KeyError:
            continue
        for summary in await runner.session_manager.list_summaries_from_disk():
            pairs.append((agent, summary))
    return pairs


async def _collect_memory(agents: list[Any]) -> list[tuple[Any, Any]]:
    registry = get_registry()
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
    return pairs


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
    file_types = {"memory": total_files} if total_files else {}
    by_agent: dict[str, tuple[str, int, int]] = {}
    for a, s in memory_pairs:
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
        items.append((s.updated_at, ActivityItem(
            ts=_ts_to_iso(s.updated_at), kind="memory", agent=a.id,
            agent_label=_agent_label(a),
            text=f"Memory {s.user_id}/MEMORY.md updated", status="ok",
        )))

    items.sort(key=lambda t: t[0], reverse=True)
    return [item for _, item in items[:_ACTIVITY_LIMIT]]


# ── Builder + cache ─────────────────────────────────────────────────


async def _build_summary() -> DashboardSummary:
    agents = await _collect_agents()
    agents_root = get_agents_root(__file__)
    skill_pairs = _collect_skills(agents_root, agents)
    tool_pairs = _collect_tools(agents_root, agents)
    session_pairs = await _collect_sessions(agents)
    memory_pairs = await _collect_memory(agents)

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


_cache: dict[str, Any] = {"payload": None, "etag": None, "at": 0.0}


async def _cached_summary() -> tuple[dict[str, Any], str]:
    """2-second TTL cache shared across all callers in this process."""
    now = time.monotonic()
    if (
        _cache["payload"] is not None
        and now - _cache["at"] <= _CACHE_TTL_SECONDS
    ):
        return _cache["payload"], _cache["etag"]

    summary = await _build_summary()
    payload = summary.model_dump(mode="json")
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    etag = '"' + hashlib.sha1(body).hexdigest() + '"'
    _cache["payload"] = payload
    _cache["etag"] = etag
    _cache["at"] = now
    return payload, etag


# ── Endpoint ────────────────────────────────────────────────────────


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
):
    payload, etag = await _cached_summary()
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=json.dumps(payload, ensure_ascii=False),
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "max-age=2"},
    )
