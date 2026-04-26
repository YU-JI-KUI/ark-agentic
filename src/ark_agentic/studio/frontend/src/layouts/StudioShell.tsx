import { NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { type CSSProperties, useEffect, useMemo, useRef, useState } from 'react'
import { api, type AgentMeta } from '../api'
import { useAuth } from '../auth'
import DecisionDock from '../components/DecisionDock'
import ThemeToggle from '../components/ThemeToggle'
import {
  LogoutIcon,
  MoreIcon,
  PlusIcon,
  RefreshIcon,
  RobotIcon,
  SearchIcon,
  SparkIcon,
} from '../components/StudioIcons'

export interface StudioShellContextValue {
  activeSection: string
  agents: AgentMeta[]
  agentsError: string | null
  agentsLoading: boolean
  refreshAgents: () => Promise<void>
  selectedAgent: AgentMeta | null
}

type StudioMainStyle = CSSProperties & {
  '--agent-radar-width': string
  '--decision-dock-width': string
}

const DEFAULT_SECTION = 'overview'
const AGENT_RADAR_MIN_WIDTH = 200
const AGENT_RADAR_MAX_WIDTH = 420
const AGENT_RADAR_DEFAULT_WIDTH = 260
const DECISION_DOCK_MIN_WIDTH = 320
const DECISION_DOCK_MAX_WIDTH = 560
const DECISION_DOCK_DEFAULT_WIDTH = 380

export default function StudioShell() {
  const { agentId, section } = useParams<{ agentId?: string; section?: string }>()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { logout, user } = useAuth()
  const [agents, setAgents] = useState<AgentMeta[]>([])
  const [agentsLoading, setAgentsLoading] = useState(true)
  const [agentsError, setAgentsError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [agentRadarWidth, setAgentRadarWidth] = useState(AGENT_RADAR_DEFAULT_WIDTH)
  const [isAgentRadarResizing, setIsAgentRadarResizing] = useState(false)
  const [decisionDockOpen, setDecisionDockOpen] = useState(false)
  const [decisionDockWidth, setDecisionDockWidth] = useState(DECISION_DOCK_DEFAULT_WIDTH)
  const agentRadarResizeRef = useRef<{ startWidth: number; startX: number } | null>(null)

  async function refreshAgents() {
    setAgentsLoading(true)
    setAgentsError(null)
    try {
      const nextAgents = await api.listAgents()
      setAgents(nextAgents)
    } catch (error) {
      setAgentsError(error instanceof Error ? error.message : String(error))
    } finally {
      setAgentsLoading(false)
    }
  }

  useEffect(() => {
    void refreshAgents()
  }, [])

  useEffect(() => {
    if (!isAgentRadarResizing) return

    function handlePointerMove(event: PointerEvent) {
      const current = agentRadarResizeRef.current
      if (!current) return
      const delta = event.clientX - current.startX
      const nextWidth = Math.min(
        AGENT_RADAR_MAX_WIDTH,
        Math.max(AGENT_RADAR_MIN_WIDTH, current.startWidth + delta),
      )
      setAgentRadarWidth(nextWidth)
    }

    function stopResizing() {
      agentRadarResizeRef.current = null
      setIsAgentRadarResizing(false)
      document.body.style.removeProperty('cursor')
      document.body.style.removeProperty('user-select')
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', stopResizing)
    window.addEventListener('pointercancel', stopResizing)

    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', stopResizing)
      window.removeEventListener('pointercancel', stopResizing)
      document.body.style.removeProperty('cursor')
      document.body.style.removeProperty('user-select')
    }
  }, [isAgentRadarResizing])

  const selectedAgent = useMemo(
    () => agents.find(agent => agent.id === agentId) ?? null,
    [agentId, agents],
  )
  const activeSection = section ?? DEFAULT_SECTION
  const filteredAgents = useMemo(() => {
    const value = query.trim().toLowerCase()
    if (!value) return agents
    return agents.filter(agent => {
      return (
        agent.name.toLowerCase().includes(value) ||
        agent.id.toLowerCase().includes(value) ||
        agent.description.toLowerCase().includes(value)
      )
    })
  }, [agents, query])

  function focusNavigate(target: string, isActive: boolean) {
    if (isActive || pathname === target) return
    void navigate(target)
  }

  const canUseDecisionDock = user?.role === 'editor'
  const showDecisionDock = canUseDecisionDock && decisionDockOpen
  const studioMainClassName = [
    'studio-main',
    showDecisionDock ? '' : 'studio-main-dock-collapsed',
  ].filter(Boolean).join(' ')
  const studioMainStyle = useMemo(
    (): StudioMainStyle => ({
      '--agent-radar-width': `${agentRadarWidth}px`,
      '--decision-dock-width': `${decisionDockWidth}px`,
    }),
    [agentRadarWidth, decisionDockWidth],
  )

  function handleAgentRadarResizeStart(event: React.PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return
    agentRadarResizeRef.current = { startWidth: agentRadarWidth, startX: event.clientX }
    setIsAgentRadarResizing(true)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  return (
    <div className="studio-shell">
      <header className="studio-topbar">
        <button className="studio-brand" onClick={() => navigate('/')} type="button">
          <div className="studio-brand-mark">
            <SparkIcon />
          </div>
          <div className="studio-brand-copy">
            <strong>Ark-Agentic Studio</strong>
            <span>Agent 协同与运行管控平台</span>
          </div>
        </button>

        <div className="cmd" aria-hidden="true">
          <SearchIcon />
          <span>Search agents, sessions, tools…</span>
          <kbd>⌘K</kbd>
        </div>

        <div className="studio-topbar-meta">
          <button className="hbtn" type="button" disabled title="Environment">
            <span className="dot" />
            Production
          </button>
          {user && <button className="hbtn" type="button">Role · {user.role}</button>}
          {user && <button className="hbtn" type="button">User · {user.display_name}</button>}
          <ThemeToggle />
          <button className="topbar-logout" onClick={logout} type="button">
            <LogoutIcon />
            Sign Out
          </button>
        </div>
      </header>

      <div
        className={studioMainClassName}
        style={studioMainStyle}
      >
        <aside
          aria-label="Agent radar"
          className={`agent-radar ${isAgentRadarResizing ? 'agent-radar-resizing' : ''}`}
        >
          <button
            aria-label="Resize agent radar"
            className="agent-radar-resize-handle"
            onPointerDown={handleAgentRadarResizeStart}
            type="button"
          />

          <div className="side-section">
            <div className="side-label">
              <span>Workspace</span>
              <div className="side-label-actions">
                <button
                  aria-label="Workspace menu"
                  className="icon-action-button"
                  type="button"
                  disabled
                  title="即将推出"
                >
                  <MoreIcon />
                </button>
              </div>
            </div>
            <NavLink
              aria-label="Workspace dashboard"
              className={({ isActive }) => `nav-item ${isActive && pathname === '/' ? 'active' : ''}`}
              to="/"
              end
            >
              <span className="nav-item-shortcut">↗</span>
              <span>Dashboard</span>
            </NavLink>
          </div>

          <div className="side-section">
            <div className="side-label">
              <span>Agents · {agents.length}</span>
              <div className="side-label-actions">
                <button
                  aria-label="Refresh agents"
                  className="icon-action-button"
                  onClick={() => void refreshAgents()}
                  title="Refresh"
                  type="button"
                >
                  <RefreshIcon />
                </button>
                <button
                  aria-label="Create new agent"
                  className="icon-action-button"
                  type="button"
                  disabled
                  title="即将推出"
                >
                  <PlusIcon />
                </button>
              </div>
            </div>
          </div>

          <label className="radar-search">
            <SearchIcon />
            <input
              aria-label="Search agents"
              onChange={event => setQuery(event.target.value)}
              placeholder="Search agents"
              value={query}
            />
          </label>

          {agentsLoading && <div className="empty-surface">正在加载 Agent...</div>}
          {agentsError && !agentsLoading && <div className="empty-surface">{agentsError}</div>}
          {!agentsLoading && !agentsError && filteredAgents.length === 0 && (
            <div className="empty-surface">没有匹配的 Agent。</div>
          )}

          <div aria-label="可用 Agent" className="agent-radar-list">
            {filteredAgents.map(agent => {
              const targetSection = activeSection === DEFAULT_SECTION ? DEFAULT_SECTION : activeSection
              const target = `/agents/${agent.id}/${targetSection}`
              const isActive = selectedAgent?.id === agent.id
              return (
                <NavLink
                  aria-label={`打开 Agent ${agent.name}`}
                  className={`agent-radar-card ${isActive ? 'active' : ''}`}
                  key={agent.id}
                  onFocus={() => focusNavigate(target, isActive)}
                  to={target}
                >
                  <div className="agent-radar-card-top">
                    <strong>{agent.name}</strong>
                    <span className="pill">{agent.id.toUpperCase()}</span>
                  </div>
                  <p>{agent.description || '暂无描述。'}</p>
                </NavLink>
              )
            })}
          </div>

          <div className="side-footer">
            <button className="sf-link" type="button" disabled title="即将推出">
              <kbd>⌘+N</kbd>
              <span>New agent</span>
            </button>
            <button className="sf-link" type="button" disabled title="即将推出">
              <kbd>?</kbd>
              <span>Documentation</span>
            </button>
            <button className="sf-link" type="button" disabled title="即将推出">
              <kbd>⚙</kbd>
              <span>Settings</span>
            </button>
          </div>
        </aside>

        <div className="studio-workspace">
          <Outlet
            context={{
              activeSection,
              agents,
              agentsError,
              agentsLoading,
              refreshAgents,
              selectedAgent,
            } satisfies StudioShellContextValue}
          />
        </div>

        <DecisionDock
          activeSection={activeSection}
          maxWidth={DECISION_DOCK_MAX_WIDTH}
          minWidth={DECISION_DOCK_MIN_WIDTH}
          onClose={() => setDecisionDockOpen(false)}
          onWidthChange={width =>
            setDecisionDockWidth(Math.min(DECISION_DOCK_MAX_WIDTH, Math.max(DECISION_DOCK_MIN_WIDTH, width)))
          }
          selectedAgent={selectedAgent}
          visible={showDecisionDock}
          width={decisionDockWidth}
        />
      </div>

      {canUseDecisionDock && !decisionDockOpen && (
        <button
          aria-label="Restore Meta-Agent dock"
          className="dock-restore-button"
          onClick={() => setDecisionDockOpen(true)}
          type="button"
        >
          <RobotIcon />
        </button>
      )}
    </div>
  )
}
