import { NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { api, type AgentMeta } from '../api'
import { useAuth } from '../auth'
import DecisionDock from '../components/DecisionDock'
import {
  AgentIcon,
  LogoutIcon,
  MemoryIcon,
  OverviewIcon,
  SearchIcon,
  SessionsIcon,
  SkillsIcon,
  SparkIcon,
  ToolsIcon,
} from '../components/StudioIcons'

export interface StudioShellContextValue {
  activeSection: string
  agents: AgentMeta[]
  refreshAgents: () => Promise<void>
  selectedAgent: AgentMeta | null
}

const DEFAULT_SECTION = 'overview'
const SECTION_ITEMS = [
  { key: 'overview', label: 'Overview', icon: OverviewIcon },
  { key: 'skills', label: 'Skills', icon: SkillsIcon },
  { key: 'tools', label: 'Tools', icon: ToolsIcon },
  { key: 'sessions', label: 'Sessions', icon: SessionsIcon },
  { key: 'memory', label: 'Memory', icon: MemoryIcon },
]

export default function StudioShell() {
  const { agentId, section } = useParams<{ agentId?: string; section?: string }>()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { logout, user } = useAuth()
  const [agents, setAgents] = useState<AgentMeta[]>([])
  const [agentsLoading, setAgentsLoading] = useState(true)
  const [agentsError, setAgentsError] = useState<string | null>(null)
  const [query, setQuery] = useState('')

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

  const sectionLinks = useMemo(() => {
    const fallbackAgent = selectedAgent ?? agents[0] ?? null
    return SECTION_ITEMS.map(item => {
      if (item.key === 'overview' && !fallbackAgent) return '/'
      if (!fallbackAgent) return '/'
      return `/agents/${fallbackAgent.id}/${item.key}`
    })
  }, [agents, selectedAgent])

  const environment = pathname.startsWith('/login') ? 'auth' : 'studio'

  function focusNavigate(target: string, isActive: boolean) {
    if (isActive || pathname === target) return
    void navigate(target)
  }

  return (
    <div className="studio-shell">
      <header className="studio-topbar">
        <button className="studio-brand" onClick={() => navigate('/')} type="button">
          <div className="studio-brand-mark">
            <SparkIcon />
          </div>
          <div>
            <strong>Ark-Agentic Studio</strong>
            <span>Mission Control with editorial precision</span>
          </div>
        </button>

        <div className="studio-topbar-meta">
          <div className="topbar-chip">
            <span className="topbar-chip-dot" />
            {environment}
          </div>
          {selectedAgent && <div className="topbar-chip">target · {selectedAgent.name}</div>}
          {user && <div className="topbar-chip">role · {user.role}</div>}
          {user && <div className="topbar-chip">user · {user.display_name}</div>}
          <button className="topbar-logout" onClick={logout} type="button">
            <LogoutIcon />
            Sign Out
          </button>
        </div>
      </header>

      <div className="studio-main">
        <aside aria-label="Studio sections" className="global-rail">
          <div className="global-rail-stack">
            {SECTION_ITEMS.map((item, index) => {
              const Icon = item.icon
              const to = sectionLinks[index]
              const isOverview = item.key === 'overview'
              const isActive =
                (isOverview && pathname === '/') ||
                (!isOverview && activeSection === item.key && Boolean(selectedAgent))
              return (
                <NavLink
                  aria-label={item.label}
                  className={`global-rail-link ${isActive ? 'active' : ''}`}
                  key={item.key}
                  onFocus={() => focusNavigate(to, isActive)}
                  to={to}
                >
                  <Icon />
                </NavLink>
              )
            })}
          </div>
          <div className="global-rail-foot">
            <AgentIcon />
          </div>
        </aside>

        <aside aria-label="Agent radar" className="agent-radar">
          <div className="surface-heading">
            <span>Agent Radar</span>
            <button
              aria-label="Refresh agents"
              className="surface-link-button"
              onClick={() => void refreshAgents()}
              type="button"
            >
              Refresh
            </button>
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

          {agentsLoading && <div className="empty-surface">Loading agents...</div>}
          {agentsError && !agentsLoading && <div className="empty-surface">{agentsError}</div>}
          {!agentsLoading && !agentsError && filteredAgents.length === 0 && (
            <div className="empty-surface">No agents matched the current filter.</div>
          )}

          <div aria-label="Available agents" className="agent-radar-list">
            {filteredAgents.map(agent => {
              const targetSection = activeSection === DEFAULT_SECTION ? DEFAULT_SECTION : activeSection
              const target = `/agents/${agent.id}/${targetSection}`
              const isActive = selectedAgent?.id === agent.id
              return (
                <NavLink
                  aria-label={`Open agent ${agent.name}`}
                  className={`agent-radar-card ${isActive ? 'active' : ''}`}
                  key={agent.id}
                  onFocus={() => focusNavigate(target, isActive)}
                  to={target}
                >
                  <div className="agent-radar-card-top">
                    <strong>{agent.name}</strong>
                  </div>
                  <p>{agent.description || 'No description provided.'}</p>
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
              refreshAgents,
              selectedAgent,
            } satisfies StudioShellContextValue}
          />
        </div>

        <DecisionDock
          activeSection={activeSection}
          selectedAgent={selectedAgent}
          visible={user?.role === 'editor'}
        />
      </div>
    </div>
  )
}
