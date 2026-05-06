import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import {
  api,
  type DashboardActivityItem,
  type DashboardDistributionItem,
  type DashboardInsightStat,
  type DashboardSummaryResponse,
  type DashboardTrendPoint,
} from '../api'
import type { StudioShellContextValue } from '../layouts/StudioShell'
import { FilterIcon, PlusIcon, RefreshIcon } from '../components/StudioIcons'

type TrendMetricKey = 'users' | 'skills' | 'tools' | 'sessions' | 'memory'

function activityKindLetter(kind: DashboardActivityItem['kind']): string {
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
  points?: DashboardTrendPoint[]
  badge?: string
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

function getTrendDelta(points: DashboardTrendPoint[]) {
  if (points.length < 2) return 0
  return points[points.length - 1].value - points[0].value
}

function getTrendDirection(points: DashboardTrendPoint[]) {
  const delta = getTrendDelta(points)
  if (delta > 0) return 'up'
  if (delta < 0) return 'down'
  return 'flat'
}

function buildPolylinePoints(points: DashboardTrendPoint[], width: number, height: number) {
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

function MiniTrendChart({ metric, points }: { metric: TrendMetricKey; points: DashboardTrendPoint[] }) {
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
            <span>{points[0]?.short_label}</span>
            <span>{points[points.length - 1]?.short_label}</span>
          </div>
        </div>
      )}
    </article>
  )
}

function InsightStatTile({ label, value, hint }: DashboardInsightStat) {
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
  items: DashboardDistributionItem[]
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

function ActivityFeed({ items }: { items: DashboardActivityItem[] }) {
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
                <span className="agent">[{it.agent_label}]</span>
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

export default function StudioDashboardPage() {
  const { agentsLoading, agentsError, refreshAgents } = useOutletContext<StudioShellContextValue>()
  const [summary, setSummary] = useState<DashboardSummaryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (agentsLoading) return

    let cancelled = false

    async function loadDashboard() {
      setLoading(true)
      setError(null)

      try {
        const next = await api.getDashboardSummary()
        if (!cancelled) {
          setSummary(next)
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
  }, [agentsLoading])

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

  const lastActivity = summary.activity[0]

  return (
    <div className="workspace-page studio-dashboard-page">
      <div className="dashboard-page-head">
        <div>
          <h1>Workspace overview</h1>
          <p>
            {summary.total_agents} agents · {formatCompactNumber(summary.total_sessions)} sessions · last activity{' '}
            {lastActivity ? `${formatActivityTime(lastActivity.ts)} ago` : '—'}
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
          value={formatCompactNumber(summary.total_agents)}
        />
        <MetricCard
          label="Total Skills"
          points={summary.trends.skills}
          tone="skills"
          value={formatCompactNumber(summary.total_skills)}
        />
        <MetricCard
          label="Total Tools"
          points={summary.trends.tools}
          tone="tools"
          value={formatCompactNumber(summary.total_tools)}
        />
        <MetricCard
          label="Total Users"
          points={summary.trends.users}
          tone="users"
          value={formatCompactNumber(summary.total_users)}
        />
        <MetricCard
          label="Total Sessions"
          points={summary.trends.sessions}
          tone="sessions"
          value={formatCompactNumber(summary.total_sessions)}
        />
        <MetricCard
          badge={formatBytes(summary.total_memory_bytes)}
          label="Total Memory"
          points={summary.trends.memory}
          tone="memory"
          value={formatCompactNumber(summary.total_memory_files)}
        />
      </section>

      <section className="dashboard-insight-grid dashboard-insight-grid-coverage">
        <article className="workspace-surface dashboard-insight-panel dashboard-insight-panel-skills metric-tone-skills">
          <div className="surface-heading dashboard-insight-heading">
            <span>Skills coverage</span>
            <b>{formatCompactNumber(summary.total_skills)} total</b>
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
            <b>{formatCompactNumber(summary.total_sessions)} total</b>
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
              items={summary.sessions.message_bands}
              title="Message Count Bands"
              tone="sessions"
            />
          </div>
        </article>
      </section>

      <section className="dashboard-row-2">
        <ActivityFeed items={summary.activity} />
      </section>
    </div>
  )
}
