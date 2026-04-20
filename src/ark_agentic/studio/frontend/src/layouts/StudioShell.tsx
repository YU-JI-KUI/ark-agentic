import { NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { type CSSProperties, useEffect, useMemo, useRef, useState } from 'react'
import { api, type AgentMeta } from '../api'
import { useAuth } from '../auth'
import DecisionDock from '../components/DecisionDock'
import {
  AgentIcon,
  LogoutIcon,
  OverviewIcon,
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
const AGENT_RADAR_MIN_WIDTH = 240
const AGENT_RADAR_MAX_WIDTH = 420
const AGENT_RADAR_DEFAULT_WIDTH = 280
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
  const [agentRadarOpen, setAgentRadarOpen] = useState(true)
  const [agentRadarWidth, setAgentRadarWidth] = useState(AGENT_RADAR_DEFAULT_WIDTH)
  const [isAgentRadarResizing, setIsAgentRadarResizing] = useState(false)
  const [decisionDockOpen, setDecisionDockOpen] = useState(true)
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
    agentRadarOpen ? '' : 'studio-main-radar-collapsed',
  ].filter(Boolean).join(' ')
  const studioMainStyle = useMemo(
    (): StudioMainStyle => ({
      '--agent-radar-width': `${agentRadarWidth}px`,
      '--decision-dock-width': `${decisionDockWidth}px`,
    }),
    [agentRadarWidth, decisionDockWidth],
  )

  function handleAgentRadarResizeStart(event: React.PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0 || !agentRadarOpen) return
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
            <span>Agent 的可视化管理与调试工作台。</span>
          </div>
        </button>

        <div className="studio-topbar-meta">
          {selectedAgent && <div className="topbar-chip">Agent · {selectedAgent.name}</div>}
          {user && <div className="topbar-chip">Role · {user.role}</div>}
          {user && <div className="topbar-chip">User · {user.display_name}</div>}
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
        <aside aria-label="Studio sections" className="global-rail">
          <div className="global-rail-stack">
            <NavLink
              aria-label="Dashboard"
              className={`global-rail-link ${pathname === '/' ? 'active' : ''}`}
              onFocus={() => focusNavigate('/', pathname === '/')}
              to="/"
            >
              <OverviewIcon />
            </NavLink>
            <button
              aria-label={agentRadarOpen ? 'Collapse agent radar' : 'Expand agent radar'}
              aria-pressed={agentRadarOpen}
              className={`global-rail-link ${agentRadarOpen ? 'active' : ''}`}
              onClick={() => setAgentRadarOpen(current => !current)}
              type="button"
            >
              <AgentIcon />
            </button>
          </div>
        </aside>

        <aside
          aria-hidden={!agentRadarOpen}
          aria-label="Agent radar"
          className={`agent-radar ${agentRadarOpen ? '' : 'agent-radar-collapsed'} ${isAgentRadarResizing ? 'agent-radar-resizing' : ''}`}
        >
            <button
              aria-label="Resize agent radar"
              className="agent-radar-resize-handle"
              onPointerDown={handleAgentRadarResizeStart}
              tabIndex={agentRadarOpen ? undefined : -1}
              type="button"
            />
            <div className="surface-heading agent-radar-heading">
              <span>Agent Radar</span>
              <button
                aria-label="Refresh agents"
                className="panel-icon-button agent-radar-refresh-button"
                onClick={() => void refreshAgents()}
                tabIndex={agentRadarOpen ? undefined : -1}
                title="Refresh agents"
                type="button"
              >
                <RefreshIcon />
              </button>
            </div>

            <label className="radar-search">
              <SearchIcon />
              <input
                aria-label="Search agents"
                onChange={event => setQuery(event.target.value)}
                placeholder="Search agents"
                tabIndex={agentRadarOpen ? undefined : -1}
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
                  tabIndex={agentRadarOpen ? undefined : -1}
                  to={target}
                >
                  <div className="agent-radar-card-top">
                      <strong>{agent.name}</strong>
                    </div>
                    <p>{agent.description || '暂无描述。'}</p>
                    <div className="agent-radar-card-meta">
                      <span>{agent.id}</span>
                    </div>
                  </NavLink>
                )
              })}
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
