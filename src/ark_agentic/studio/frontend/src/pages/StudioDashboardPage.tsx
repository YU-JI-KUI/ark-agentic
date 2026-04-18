import { NavLink, useOutletContext } from 'react-router-dom'
import type { StudioShellContextValue } from '../layouts/StudioShell'

function wasUpdatedRecently(value: string, withinDays: number) {
  if (!value) return false
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return false
  return Date.now() - parsed.getTime() <= withinDays * 24 * 60 * 60 * 1000
}

function formatAgentDate(value: string) {
  if (!value) return 'updated unknown'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'updated unknown'
  return `updated ${parsed.toLocaleDateString()}`
}

export default function StudioDashboardPage() {
  const { agents } = useOutletContext<StudioShellContextValue>()

  const describedCount = agents.filter(agent => Boolean(agent.description?.trim())).length
  const recentlyUpdatedCount = agents.filter(agent => wasUpdatedRecently(agent.updated_at, 30)).length

  return (
    <div className="workspace-page">
      <section className="hero-surface">
        <div className="hero-surface-copy">
          <div className="surface-kicker">Overview</div>
          <h1>Agent control, direct execution, and traceable operations.</h1>
          <p>
            This Studio direction is built as a control plane, not a CRUD shell.
            Pick an agent to review assets, validate changes, inspect session evidence, and guide the Meta-Agent with explicit intent.
          </p>
        </div>

        <div className="hero-surface-grid">
          <div className="metric-surface">
            <span>Total Agents</span>
            <strong>{agents.length}</strong>
            <p>All registered agents visible in the current workspace.</p>
          </div>
          <div className="metric-surface">
            <span>Documented</span>
            <strong>{describedCount}</strong>
            <p>Agents with human-written descriptions that explain their operating scope.</p>
          </div>
          <div className="metric-surface">
            <span>Updated 30d</span>
            <strong>{recentlyUpdatedCount}</strong>
            <p>Agents with metadata updated in the last 30 days.</p>
          </div>
        </div>
      </section>

      <section className="workspace-grid-two">
        <article className="workspace-surface">
          <div className="surface-heading">
            <span>Operating Principles</span>
          </div>
          <div className="principle-grid">
            <div className="principle-card">
              <strong>Context stays visible</strong>
              <p>Agent identity, active surface, and user role stay present so edits never feel detached from target context.</p>
            </div>
            <div className="principle-card">
              <strong>AI proposes, humans decide</strong>
              <p>The Meta-Agent is tuned for concrete operational guidance and implementation support, not ambient chat.</p>
            </div>
            <div className="principle-card">
              <strong>Evidence is first-class</strong>
              <p>Sessions, memory, and tools are treated as linked evidence surfaces rather than buried subpages.</p>
            </div>
          </div>
        </article>

        <article className="workspace-surface">
          <div className="surface-heading">
            <span>Quick Start</span>
          </div>
          <div className="signal-list">
            <div className="signal-card">
              <strong>1. Select an agent</strong>
              <p>Use Agent Radar to lock into a specific operating context before changing assets.</p>
            </div>
            <div className="signal-card">
              <strong>2. Open the target surface</strong>
              <p>Switch directly into skills, tools, sessions, or memory using the left rail.</p>
            </div>
            <div className="signal-card">
              <strong>3. Use the Decision Dock</strong>
              <p>Ask for impact review, draft changes, or follow-up implementation steps anchored to the current surface.</p>
            </div>
          </div>
        </article>
      </section>

      <section className="workspace-surface">
        <div className="surface-heading">
          <span>Agent Directory</span>
          <span>{agents.length} visible</span>
        </div>
        <div className="dashboard-agent-grid">
          {agents.map(agent => (
            <NavLink className="dashboard-agent-card" key={agent.id} to={`/agents/${agent.id}/overview`}>
              <div className="dashboard-agent-card-top">
                <strong>{agent.name}</strong>
              </div>
              <p>{agent.description || 'No description provided.'}</p>
              <div className="dashboard-agent-card-meta">
                <span>{agent.id}</span>
                <span>{formatAgentDate(agent.updated_at)}</span>
              </div>
            </NavLink>
          ))}
        </div>
      </section>
    </div>
  )
}
