import { useEffect, useMemo, useState } from 'react'
import { NavLink, useOutletContext } from 'react-router-dom'
import {
  api,
  type AgentMeta,
  type MemoryFileItem,
  type SessionItem,
  type SkillMeta,
  type ToolMeta,
} from '../api'
import type { StudioShellContextValue } from '../layouts/StudioShell'
import { FilterIcon, PlusIcon, RefreshIcon } from '../components/StudioIcons'

type TrendMetricKey = 'users' | 'skills' | 'tools' | 'sessions' | 'memory'

type TrendPoint = {
  label: string
  shortLabel: string
  value: number
}

type DistributionItem = {
  label: string
  value: number
  hint?: string
}

type InsightStat = {
  label: string
  value: string
  hint?: string
}

type AgentSnapshot = {
  agent: AgentMeta
  skills: SkillMeta[]
  tools: ToolMeta[]
  sessions: SessionItem[]
  memoryFiles: MemoryFileItem[]
}

type DashboardSummary = {
  totalAgents: number
  totalUsers: number
  totalSkills: number
  totalTools: number
  totalSessions: number
  totalMemoryFiles: number
  totalMemoryBytes: number
  trends: Record<TrendMetricKey, TrendPoint[]>
  skills: {
    stats: InsightStat[]
    groups: DistributionItem[]
    tags: DistributionItem[]
  }
  tools: {
    stats: InsightStat[]
    groups: DistributionItem[]
    agents: DistributionItem[]
  }
  sessions: {
    stats: InsightStat[]
    agents: DistributionItem[]
    messageBands: DistributionItem[]
  }
  memory: {
    stats: InsightStat[]
    fileTypes: DistributionItem[]
    agents: DistributionItem[]
  }
}

type ActivityKind = 'skill' | 'tool' | 'session' | 'memory'
type ActivityStatus = 'ok' | 'warn' | 'error'
type ActivityItem = {
  ts: string
  kind: ActivityKind
  agent: string
  agentLabel: string
  text: string
  status: ActivityStatus
}

function buildActivityFeed(snapshots: AgentSnapshot[], limit = 12): ActivityItem[] {
  const items: ActivityItem[] = []
  for (const snap of snapshots) {
    const agentLabel = snap.agent.name || snap.agent.id
    snap.skills.forEach(skill => {
      if (!skill.modified_at) return
      items.push({
        ts: skill.modified_at,
        kind: 'skill',
        agent: snap.agent.id,
        agentLabel,
        text: `Skill ${skill.name} updated`,
        status: 'ok',
      })
    })
    snap.tools.forEach(tool => {
      if (!tool.modified_at) return
      items.push({
        ts: tool.modified_at,
        kind: 'tool',
        agent: snap.agent.id,
        agentLabel,
        text: `Tool ${tool.name} updated`,
        status: 'ok',
      })
    })
    snap.sessions.forEach(session => {
      const ts = session.updated_at ?? session.created_at
      if (!ts) return
      items.push({
        ts,
        kind: 'session',
        agent: snap.agent.id,
        agentLabel,
        text: `Session ${session.session_id.slice(0, 8)} (${session.message_count} msgs)`,
        status: session.message_count === 0 ? 'warn' : 'ok',
      })
    })
    snap.memoryFiles.forEach(file => {
      if (!file.modified_at) return
      items.push({
        ts: file.modified_at,
        kind: 'memory',
        agent: snap.agent.id,
        agentLabel,
        text: `Memory ${file.file_path} updated`,
        status: 'ok',
      })
    })
  }
  return items
    .sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0))
    .slice(0, limit)
}

function activityKindLetter(kind: ActivityKind): string {
  switch (kind) {
    case 'skill': return 'K'
    case 'tool': return 'T'
    case 'session': return 'S'
    case 'memory': return 'M'
  }
}

function formatActivityTime(ts: string): string {
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return '—'
  const diff = Date.now() - date.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  return `${days}d`
}

type MetricCardProps = {
  tone: TrendMetricKey | 'agents'
  label: string
  value: string
  points?: TrendPoint[]
  badge?: string
}

const TREND_MONTH_COUNT = 6
function isValidDate(value: string | null | undefined) {
  if (!value) return false
  return !Number.isNaN(Date.parse(value))
}

function formatCompactNumber(value: number) {
  return new Intl.NumberFormat('zh-CN', {
    notation: value >= 1000 ? 'compact' : 'standard',
    maximumFractionDigits: value >= 1000 ? 1 : 0,
  }).format(value)
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function formatRatio(part: number, total: number) {
  if (total <= 0) return '0%'
  return `${Math.round((part / total) * 100)}%`
}

function getMonthBuckets(count: number) {
  const now = new Date()
  const currentMonth = new Date(now.getFullYear(), now.getMonth(), 1)

  return Array.from({ length: count }, (_, index) => {
    const monthStart = new Date(currentMonth.getFullYear(), currentMonth.getMonth() - (count - 1 - index), 1)
    const monthEnd = new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 0, 23, 59, 59, 999)
    return {
      label: monthStart.toLocaleDateString('zh-CN', { month: 'short', year: 'numeric' }),
      shortLabel: monthStart.toLocaleDateString('zh-CN', { month: 'short' }),
      end: monthEnd.getTime(),
    }
  })
}

function buildCumulativeTrend(
  items: Array<string | null | undefined>,
  count: number,
): TrendPoint[] {
  const buckets = getMonthBuckets(count)
  const parsed = items
    .map(value => (isValidDate(value) ? Date.parse(value as string) : null))
    .filter((value): value is number => value !== null)
    .sort((left, right) => left - right)

  let pointer = 0

  return buckets.map(bucket => {
    while (pointer < parsed.length && parsed[pointer] <= bucket.end) {
      pointer += 1
    }

    return {
      label: bucket.label,
      shortLabel: bucket.shortLabel,
      value: pointer,
    }
  })
}

function getTrendDelta(points: TrendPoint[]) {
  if (points.length < 2) return 0
  return points[points.length - 1].value - points[0].value
}

function getTrendDirection(points: TrendPoint[]) {
  const delta = getTrendDelta(points)
  if (delta > 0) return 'up'
  if (delta < 0) return 'down'
  return 'flat'
}

function buildPolylinePoints(points: TrendPoint[], width: number, height: number) {
  if (points.length === 0) return ''
  if (points.length === 1) return `0,${height / 2}`

  const maxValue = Math.max(...points.map(point => point.value), 1)

  return points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * width
      const y = height - (point.value / maxValue) * height
      return `${x},${y}`
    })
    .join(' ')
}

function incrementCount(map: Map<string, number>, label: string, amount = 1) {
  map.set(label, (map.get(label) || 0) + amount)
}

function sortDistribution(
  entries: Iterable<[string, number]>,
  limit = 6,
  hintBuilder?: (label: string, value: number) => string | undefined,
) {
  return Array.from(entries)
    .filter(([, value]) => value > 0)
    .map(([label, value]) => ({
      label,
      value,
      hint: hintBuilder?.(label, value),
    }))
    .sort((left, right) => right.value - left.value || left.label.localeCompare(right.label, 'zh-CN'))
    .slice(0, limit)
}

function MiniTrendChart({ metric, points }: { metric: TrendMetricKey; points: TrendPoint[] }) {
  if (points.length === 0) return <div className="dashboard-chart-empty">No trend</div>

  const width = 132
  const height = 44
  const polyline = buildPolylinePoints(points, width, height)
  const area = `${polyline} ${width},${height} 0,${height}`

  return (
    <svg aria-hidden="true" className={`mini-trend-chart metric-tone-${metric}`} viewBox={`0 0 ${width} ${height}`}>
      <polygon className="mini-trend-area" points={area} />
      <polyline className="mini-trend-line" fill="none" points={polyline} />
    </svg>
  )
}

function MetricCard({ tone, label, value, points, badge }: MetricCardProps) {
  const direction = points ? getTrendDirection(points) : null
  const delta = points ? getTrendDelta(points) : 0
  const trendLabel = points && points.length > 1
    ? `${delta >= 0 ? '+' : ''}${formatCompactNumber(delta)} in ${points.length}m`
    : null

  return (
    <article className={`workspace-surface dashboard-metric-card metric-tone-${tone}`}>
      <div className="dashboard-metric-card-head">
        <span>{label}</span>
        {badge && <b>{badge}</b>}
      </div>
      <div className="dashboard-metric-card-main">
        <strong>{value}</strong>
        {trendLabel && <div className={`dashboard-metric-delta trend-${direction}`}>{trendLabel}</div>}
      </div>
      {points && (
        <div className="dashboard-card-trend">
          <MiniTrendChart metric={tone === 'agents' ? 'users' : tone} points={points} />
          <div className="dashboard-card-trend-labels" aria-hidden="true">
            <span>{points[0]?.shortLabel}</span>
            <span>{points[points.length - 1]?.shortLabel}</span>
          </div>
        </div>
      )}
    </article>
  )
}

function InsightStatTile({ label, value, hint }: InsightStat) {
  return (
    <div className="dashboard-insight-stat">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  )
}

function DistributionCard({
  title,
  items,
  emptyLabel,
  tone,
  valueFormatter = formatCompactNumber,
}: {
  title: string
  items: DistributionItem[]
  emptyLabel: string
  tone: TrendMetricKey | 'agents'
  valueFormatter?: (value: number) => string
}) {
  if (items.length === 0) {
    return (
      <section className={`dashboard-distribution-card metric-tone-${tone}`}>
        <div className="dashboard-distribution-head">
          <strong>{title}</strong>
        </div>
        <div className="dashboard-chart-empty">{emptyLabel}</div>
      </section>
    )
  }

  const maxValue = Math.max(...items.map(item => item.value), 1)

  return (
    <section className={`dashboard-distribution-card metric-tone-${tone}`}>
      <div className="dashboard-distribution-head">
        <strong>{title}</strong>
      </div>
      <div className="dashboard-distribution-list">
        {items.map(item => {
          const width = `${Math.max((item.value / maxValue) * 100, 6)}%`
          return (
            <div className="dashboard-distribution-item" key={item.label}>
              <div className="dashboard-distribution-item-head">
                <div className="dashboard-distribution-copy">
                  <span title={item.label}>{item.label}</span>
                  {item.hint && <small>{item.hint}</small>}
                </div>
                <strong>{valueFormatter(item.value)}</strong>
              </div>
              <div className="dashboard-distribution-bar">
                <div className="dashboard-distribution-bar-fill" style={{ width }} />
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

async function loadDashboardSnapshots(agents: AgentMeta[]): Promise<AgentSnapshot[]> {
  return Promise.all(
    agents.map(async agent => {
      const [skillsResult, toolsResult, sessionsResult, memoryResult] = await Promise.allSettled([
        api.listSkills(agent.id),
        api.listTools(agent.id),
        api.listSessions(agent.id),
        api.listMemoryFiles(agent.id),
      ])

      const skills = skillsResult.status === 'fulfilled' ? skillsResult.value : []
      const tools = toolsResult.status === 'fulfilled' ? toolsResult.value : []
      const sessions = sessionsResult.status === 'fulfilled' ? sessionsResult.value : []
      const memoryFiles = memoryResult.status === 'fulfilled' ? memoryResult.value : []

      return {
        agent,
        skills,
        tools,
        sessions,
        memoryFiles,
      }
    }),
  )
}

function buildDashboardSummary(snapshots: AgentSnapshot[]): DashboardSummary {
  const agents = snapshots.map(snapshot => snapshot.agent)

  const allSkills = snapshots.flatMap(snapshot => snapshot.skills.map(skill => ({ skill, agent: snapshot.agent })))
  const allTools = snapshots.flatMap(snapshot => snapshot.tools.map(tool => ({ tool, agent: snapshot.agent })))
  const allSessions = snapshots.flatMap(snapshot => snapshot.sessions)
  const allMemoryFiles = snapshots.flatMap(snapshot => snapshot.memoryFiles)
  const userFirstSeen = new Map<string, number>()
  const sessionUsers = new Set<string>()
  const memoryUsers = new Set<string>()
  const skillGroupCounts = new Map<string, number>()
  const skillTagCounts = new Map<string, number>()
  const toolGroupCounts = new Map<string, number>()
  const fileTypeCounts = new Map<string, number>()
  const messageBandCounts = new Map<string, number>([
    ['0 messages', 0],
    ['1-5 messages', 0],
    ['6-20 messages', 0],
    ['21+ messages', 0],
  ])
  const agentsWithSkills = snapshots.filter(snapshot => snapshot.skills.length > 0).length
  const agentsWithTools = snapshots.filter(snapshot => snapshot.tools.length > 0).length
  const agentsWithSessions = snapshots.filter(snapshot => snapshot.sessions.length > 0).length
  const agentsWithMemory = snapshots.filter(snapshot => snapshot.memoryFiles.length > 0).length
  const groupedSkillsCount = allSkills.filter(({ skill }) => Boolean(skill.group?.trim())).length
  const taggedSkillsCount = allSkills.filter(({ skill }) => (skill.tags?.filter(Boolean).length || 0) > 0).length
  const documentedToolsCount = allTools.filter(({ tool }) => Boolean(tool.description?.trim())).length
  const typedToolsCount = allTools.filter(({ tool }) => Object.keys(tool.parameters || {}).length > 0).length
  const sessionsWithMessagesCount = allSessions.filter(session => session.message_count > 0).length
  const totalMessageCount = allSessions.reduce((sum, session) => sum + session.message_count, 0)

  function trackUser(userId: string, timestamp: string | null | undefined) {
    const normalized = userId.trim()
    if (!normalized || !isValidDate(timestamp)) return
    const parsed = Date.parse(timestamp as string)
    const current = userFirstSeen.get(normalized)
    if (current === undefined || parsed < current) {
      userFirstSeen.set(normalized, parsed)
    }
  }

  allSessions.forEach(session => {
    if (session.user_id?.trim()) sessionUsers.add(session.user_id.trim())
    trackUser(session.user_id, session.created_at ?? session.updated_at)

    if (session.message_count <= 0) incrementCount(messageBandCounts, '0 messages')
    else if (session.message_count <= 5) incrementCount(messageBandCounts, '1-5 messages')
    else if (session.message_count <= 20) incrementCount(messageBandCounts, '6-20 messages')
    else incrementCount(messageBandCounts, '21+ messages')
  })

  allMemoryFiles.forEach(file => {
    if (file.user_id?.trim()) memoryUsers.add(file.user_id.trim())
    trackUser(file.user_id, file.modified_at)
    incrementCount(fileTypeCounts, file.file_type?.trim() || 'unknown')
  })

  allSkills.forEach(({ skill }) => {
    incrementCount(skillGroupCounts, skill.group?.trim() || 'ungrouped')

    const tags = skill.tags?.map(tag => tag.trim()).filter(Boolean) || []
    if (tags.length === 0) {
      incrementCount(skillTagCounts, 'untagged')
      return
    }
    tags.forEach(tag => incrementCount(skillTagCounts, tag))
  })

  allTools.forEach(({ tool }) => {
    incrementCount(toolGroupCounts, tool.group?.trim() || 'ungrouped')
  })

  return {
    totalAgents: agents.length,
    totalUsers: userFirstSeen.size,
    totalSkills: allSkills.length,
    totalTools: allTools.length,
    totalSessions: allSessions.length,
    totalMemoryFiles: allMemoryFiles.length,
    totalMemoryBytes: allMemoryFiles.reduce((sum, file) => sum + file.size_bytes, 0),
    trends: {
      users: buildCumulativeTrend(
        Array.from(userFirstSeen.values()).map(value => new Date(value).toISOString()),
        TREND_MONTH_COUNT,
      ),
      skills: buildCumulativeTrend(
        allSkills.map(({ skill, agent }) => skill.modified_at ?? agent.updated_at),
        TREND_MONTH_COUNT,
      ),
      tools: buildCumulativeTrend(
        allTools.map(({ tool, agent }) => tool.modified_at ?? agent.updated_at),
        TREND_MONTH_COUNT,
      ),
      sessions: buildCumulativeTrend(
        allSessions.map(session => session.created_at ?? session.updated_at),
        TREND_MONTH_COUNT,
      ),
      memory: buildCumulativeTrend(
        allMemoryFiles.map(file => file.modified_at),
        TREND_MONTH_COUNT,
      ),
    },
    skills: {
      stats: [
        {
          label: 'Agents Covered',
          value: `${agentsWithSkills}/${agents.length}`,
          hint: formatRatio(agentsWithSkills, agents.length),
        },
        {
          label: 'Grouped Skills',
          value: `${groupedSkillsCount}/${allSkills.length}`,
          hint: formatRatio(groupedSkillsCount, allSkills.length),
        },
        {
          label: 'Tagged Skills',
          value: `${taggedSkillsCount}/${allSkills.length}`,
          hint: formatRatio(taggedSkillsCount, allSkills.length),
        },
      ],
      groups: sortDistribution(
        skillGroupCounts.entries(),
        6,
        (_, value) => formatRatio(value, allSkills.length),
      ),
      tags: sortDistribution(
        skillTagCounts.entries(),
        6,
        (_, value) => formatRatio(value, allSkills.length),
      ),
    },
    tools: {
      stats: [
        {
          label: 'Agents Covered',
          value: `${agentsWithTools}/${agents.length}`,
          hint: formatRatio(agentsWithTools, agents.length),
        },
        {
          label: 'Documented',
          value: `${documentedToolsCount}/${allTools.length}`,
          hint: formatRatio(documentedToolsCount, allTools.length),
        },
        {
          label: 'Schema Ready',
          value: `${typedToolsCount}/${allTools.length}`,
          hint: formatRatio(typedToolsCount, allTools.length),
        },
      ],
      groups: sortDistribution(
        toolGroupCounts.entries(),
        6,
        (_, value) => formatRatio(value, allTools.length),
      ),
      agents: snapshots
        .map(snapshot => ({
          label: snapshot.agent.name || snapshot.agent.id,
          value: snapshot.tools.length,
          hint: snapshot.tools.length > 0 ? snapshot.agent.id : 'no tools',
        }))
        .filter(item => item.value > 0)
        .sort((left, right) => right.value - left.value || left.label.localeCompare(right.label, 'zh-CN'))
        .slice(0, 6),
    },
    sessions: {
      stats: [
        {
          label: 'Agents Covered',
          value: `${agentsWithSessions}/${agents.length}`,
          hint: formatRatio(agentsWithSessions, agents.length),
        },
        {
          label: 'Users Covered',
          value: formatCompactNumber(sessionUsers.size),
          hint: 'distinct users',
        },
        {
          label: 'Non-empty Sessions',
          value: `${sessionsWithMessagesCount}/${allSessions.length}`,
          hint: formatRatio(sessionsWithMessagesCount, allSessions.length),
        },
        {
          label: 'Avg Msg / Session',
          value: allSessions.length > 0 ? `${(totalMessageCount / allSessions.length).toFixed(1)}` : '0',
          hint: `${formatCompactNumber(totalMessageCount)} messages`,
        },
      ],
      agents: snapshots
        .map(snapshot => ({
          label: snapshot.agent.name || snapshot.agent.id,
          value: snapshot.sessions.length,
          hint:
            snapshot.sessions.length > 0
              ? `${formatCompactNumber(snapshot.sessions.reduce((sum, session) => sum + session.message_count, 0))} msgs`
              : 'no sessions',
        }))
        .filter(item => item.value > 0)
        .sort((left, right) => right.value - left.value || left.label.localeCompare(right.label, 'zh-CN'))
        .slice(0, 6),
      messageBands: sortDistribution(
        messageBandCounts.entries(),
        4,
        (_, value) => formatRatio(value, allSessions.length),
      ),
    },
    memory: {
      stats: [
        {
          label: 'Agents Covered',
          value: `${agentsWithMemory}/${agents.length}`,
          hint: formatRatio(agentsWithMemory, agents.length),
        },
        {
          label: 'Users Covered',
          value: formatCompactNumber(memoryUsers.size),
          hint: 'memory users',
        },
        {
          label: 'Storage',
          value: formatBytes(allMemoryFiles.reduce((sum, file) => sum + file.size_bytes, 0)),
          hint: `${formatCompactNumber(allMemoryFiles.length)} files`,
        },
        {
          label: 'File Types',
          value: formatCompactNumber(fileTypeCounts.size),
          hint: 'distinct types',
        },
      ],
      fileTypes: sortDistribution(
        fileTypeCounts.entries(),
        6,
        (_, value) => formatRatio(value, allMemoryFiles.length),
      ),
      agents: snapshots
        .map(snapshot => ({
          label: snapshot.agent.name || snapshot.agent.id,
          value: snapshot.memoryFiles.reduce((sum, file) => sum + file.size_bytes, 0),
          hint: `${formatCompactNumber(snapshot.memoryFiles.length)} files`,
        }))
        .filter(item => item.value > 0)
        .sort((left, right) => right.value - left.value || left.label.localeCompare(right.label, 'zh-CN'))
        .slice(0, 6),
    },
  }
}

function ActivityFeed({ items }: { items: ActivityItem[] }) {
  const [filter, setFilter] = useState<'all' | 'session' | 'tool' | 'memory'>('all')
  const visible = filter === 'all' ? items : items.filter(i => i.kind === filter)

  return (
    <article className="workspace-surface">
      <div className="surface-heading">
        <span>Activity</span>
        <div className="button-row">
          <button className={`chip ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')} type="button">All</button>
          <button className={`chip ${filter === 'session' ? 'active' : ''}`} onClick={() => setFilter('session')} type="button">Sessions</button>
          <button className={`chip ${filter === 'tool' ? 'active' : ''}`} onClick={() => setFilter('tool')} type="button">Tools</button>
          <button className={`chip ${filter === 'memory' ? 'active' : ''}`} onClick={() => setFilter('memory')} type="button">Memory</button>
        </div>
      </div>
      {visible.length === 0 ? (
        <div className="empty-surface">No recent activity.</div>
      ) : (
        <div className="activity">
          {visible.map((it, idx) => (
            <div className="act-row" key={`${it.ts}-${it.agent}-${it.kind}-${idx}`}>
              <div className="act-time">{formatActivityTime(it.ts)}</div>
              <div className={`act-icon ${it.status}`}>{activityKindLetter(it.kind)}</div>
              <div className="act-text">
                <span className="agent">[{it.agentLabel}]</span>
                {it.text}
              </div>
              <div className="act-kind">{it.kind}</div>
            </div>
          ))}
        </div>
      )}
    </article>
  )
}

function buildAgentSparkline(snap: AgentSnapshot, buckets = 9, days = 14): { points: number[]; warn: boolean } {
  const now = Date.now()
  const start = now - days * 86_400_000
  const buckSize = (now - start) / buckets
  const counts = new Array(buckets).fill(0) as number[]
  let warn = false
  for (const session of snap.sessions) {
    if (session.message_count === 0) warn = true
    const ts = Date.parse(session.updated_at ?? session.created_at ?? '')
    if (Number.isNaN(ts) || ts < start || ts > now) continue
    const idx = Math.min(buckets - 1, Math.max(0, Math.floor((ts - start) / buckSize)))
    counts[idx] += 1
  }
  return { points: counts, warn }
}

function AgentHealthList({ snapshots }: { snapshots: AgentSnapshot[] }) {
  return (
    <article className="workspace-surface">
      <div className="surface-heading">
        <span>Agents · health</span>
        <span>{snapshots.length}</span>
      </div>
      <div>
        {snapshots.map(snap => {
          const { points, warn } = buildAgentSparkline(snap)
          const max = Math.max(1, ...points)
          const w = 80
          const h = 22
          const polyline = points.map((v, i) => {
            const x = points.length > 1 ? (i / (points.length - 1)) * w : 0
            const y = h - (v / max) * (h - 4) - 2
            return `${x.toFixed(1)},${y.toFixed(1)}`
          }).join(' ')
          return (
            <NavLink
              className="agent-health-card"
              key={snap.agent.id}
              to={`/agents/${snap.agent.id}/overview`}
            >
              <div className="agent-health-card-top">
                <div>
                  <div className="agent-health-card-name">{snap.agent.name}</div>
                  <div className="agent-health-card-desc">{snap.agent.description || ' '}</div>
                </div>
                <span className="badge accent">{snap.agent.id.toUpperCase()}</span>
              </div>
              <div className="agent-health-stats">
                <div className="agent-health-stat">
                  <strong>{snap.skills.length}</strong>
                  <span>skills</span>
                </div>
                <div className="agent-health-stat">
                  <strong>{snap.tools.length}</strong>
                  <span>tools</span>
                </div>
                <div className="agent-health-stat">
                  <strong>{snap.sessions.length}</strong>
                  <span>sessions</span>
                </div>
                <div className="agent-health-stat">
                  <strong>{snap.memoryFiles.length}</strong>
                  <span>memory</span>
                </div>
                <svg className="agent-health-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
                  <polyline
                    fill="none"
                    points={polyline}
                    stroke={warn ? 'var(--warn)' : 'var(--ok)'}
                    strokeWidth="1.4"
                    vectorEffect="non-scaling-stroke"
                  />
                </svg>
              </div>
            </NavLink>
          )
        })}
        {snapshots.length === 0 && <div className="empty-surface">No agents.</div>}
      </div>
    </article>
  )
}

export default function StudioDashboardPage() {
  const { agents, agentsLoading, agentsError, refreshAgents } = useOutletContext<StudioShellContextValue>()
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [snapshots, setSnapshots] = useState<AgentSnapshot[]>([])
  const activityItems = useMemo(() => buildActivityFeed(snapshots, 12), [snapshots])

  useEffect(() => {
    if (agentsLoading) return

    let cancelled = false

    async function loadDashboard() {
      setLoading(true)
      setError(null)

      try {
        const nextSnapshots = await loadDashboardSnapshots(agents)
        if (!cancelled) {
          setSnapshots(nextSnapshots)
          setSummary(buildDashboardSummary(nextSnapshots))
        }
      } catch (nextError) {
        if (!cancelled) {
          setError(nextError instanceof Error ? nextError.message : String(nextError))
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadDashboard()

    return () => {
      cancelled = true
    }
  }, [agents, agentsLoading])

  if (agentsLoading || loading) {
    return (
      <div className="workspace-page studio-dashboard-page">
        <section className="workspace-surface dashboard-loading-state">
          <div className="surface-heading">
            <span>Dashboard</span>
          </div>
          <h1>Loading studio telemetry...</h1>
          <p>Collecting agents, skills, tools, sessions, and memory snapshots across the current workspace.</p>
        </section>
      </div>
    )
  }

  if (agentsError || error) {
    return (
      <div className="workspace-page studio-dashboard-page">
        <section className="workspace-surface dashboard-loading-state">
          <div className="surface-heading">
            <span>Dashboard</span>
          </div>
          <h1>Unable to load dashboard</h1>
          <p>{agentsError ?? error}</p>
        </section>
      </div>
    )
  }

  if (!summary) {
    return (
      <div className="workspace-page studio-dashboard-page">
        <section className="workspace-surface dashboard-loading-state">
          <div className="surface-heading">
            <span>Dashboard</span>
          </div>
          <h1>No studio data available</h1>
          <p>Refresh the agent registry and try again.</p>
        </section>
      </div>
    )
  }

  return (
    <div className="workspace-page studio-dashboard-page">
      <div className="dashboard-page-head">
        <div>
          <h1>Workspace overview</h1>
          <p>
            {summary.totalAgents} agents · {formatCompactNumber(summary.totalSessions)} sessions · last activity{' '}
            {activityItems[0] ? `${formatActivityTime(activityItems[0].ts)} ago` : '—'}
          </p>
        </div>
        <div className="dashboard-page-head-actions">
          <button className="btn btn-sm" onClick={() => void refreshAgents()} type="button">
            <RefreshIcon /> Refresh
          </button>
          <button className="btn btn-sm" disabled type="button" title="即将推出">
            <FilterIcon /> Last 14 days
          </button>
          <button className="btn btn-accent btn-sm" disabled type="button" title="即将推出">
            <PlusIcon /> New agent
          </button>
        </div>
      </div>

      <section className="dashboard-metric-grid">
        <MetricCard
          label="Total Agents"
          tone="agents"
          value={formatCompactNumber(summary.totalAgents)}
        />
        <MetricCard
          label="Total Skills"
          points={summary.trends.skills}
          tone="skills"
          value={formatCompactNumber(summary.totalSkills)}
        />
        <MetricCard
          label="Total Tools"
          points={summary.trends.tools}
          tone="tools"
          value={formatCompactNumber(summary.totalTools)}
        />
        <MetricCard
          label="Total Users"
          points={summary.trends.users}
          tone="users"
          value={formatCompactNumber(summary.totalUsers)}
        />
        <MetricCard
          label="Total Sessions"
          points={summary.trends.sessions}
          tone="sessions"
          value={formatCompactNumber(summary.totalSessions)}
        />
        <MetricCard
          badge={formatBytes(summary.totalMemoryBytes)}
          label="Total Memory"
          points={summary.trends.memory}
          tone="memory"
          value={formatCompactNumber(summary.totalMemoryFiles)}
        />
      </section>

      <section className="dashboard-row-2">
        <ActivityFeed items={activityItems} />
        <AgentHealthList snapshots={snapshots} />
      </section>

      <section className="dashboard-insight-grid dashboard-insight-grid-coverage">
        <article className="workspace-surface dashboard-insight-panel dashboard-insight-panel-skills metric-tone-skills">
          <div className="surface-heading dashboard-insight-heading">
            <span>Skills coverage</span>
            <b>{formatCompactNumber(summary.totalSkills)} total</b>
          </div>
          <div className="dashboard-insight-stat-grid dashboard-insight-stat-grid-skills">
            {summary.skills.stats.map(stat => (
              <InsightStatTile {...stat} key={stat.label} />
            ))}
          </div>
          <div className="dashboard-distribution-grid">
            <DistributionCard
              emptyLabel="No skill groups"
              items={summary.skills.groups}
              title="Group Distribution"
              tone="skills"
            />
            <DistributionCard
              emptyLabel="No skill tags"
              items={summary.skills.tags}
              title="Tag Distribution"
              tone="skills"
            />
          </div>
        </article>

        <article className="workspace-surface dashboard-insight-panel dashboard-insight-panel-sessions metric-tone-sessions">
          <div className="surface-heading dashboard-insight-heading">
            <span>Sessions coverage</span>
            <b>{formatCompactNumber(summary.totalSessions)} total</b>
          </div>
          <div className="dashboard-insight-stat-grid">
            {summary.sessions.stats.map(stat => (
              <InsightStatTile {...stat} key={stat.label} />
            ))}
          </div>
          <div className="dashboard-distribution-grid dashboard-distribution-grid-stacked">
            <DistributionCard
              emptyLabel="No sessions yet"
              items={summary.sessions.agents}
              title="Sessions by Agent"
              tone="sessions"
            />
            <DistributionCard
              emptyLabel="No session messages"
              items={summary.sessions.messageBands}
              title="Message Count Bands"
              tone="sessions"
            />
          </div>
        </article>
      </section>
    </div>
  )
}
