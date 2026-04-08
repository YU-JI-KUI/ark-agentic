import { useEffect, useState } from 'react'
import { Outlet, NavLink, useParams, useNavigate } from 'react-router-dom'
import { api, type AgentMeta } from '../api'
import { useAuth } from '../auth'
import ChatPanel from '../pages/ChatPanel'

export default function StudioLayout() {
    const { agentId } = useParams<{ agentId: string }>()
    const { user, logout } = useAuth()
    const navigate = useNavigate()
    const [agents, setAgents] = useState<AgentMeta[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        api.listAgents()
            .then(setAgents)
            .catch(e => setError(e.message))
            .finally(() => setLoading(false))
    }, [])

    const selectedAgentId = agentId ?? null
    const isEditor = user?.role === 'editor'
    const [luiHidden, setLuiHidden] = useState(false)

    const handleLogout = () => {
        logout()
        navigate('/login', { replace: true })
    }

    return (
        <div className="agent-shell">
            <div className="agent-topbar">
                <NavLink to="/" className="back-btn" style={{ textDecoration: 'none' }}>
                    Ark-Agentic Studio
                </NavLink>
                {selectedAgentId && (
                    <div className="agent-context-tag">
                        Target Agent: <span>{selectedAgentId}</span>
                    </div>
                )}
                {user && (
                    <div className="topbar-user">
                        <span className={`topbar-role-badge topbar-role-${user.role}`}>
                            {user.role}
                        </span>
                        <span className="topbar-username">{user.display_name}</span>
                        <button type="button" className="topbar-logout" onClick={handleLogout}>
                            Sign Out
                        </button>
                    </div>
                )}
            </div>

            <div className="main-layout">
                <aside className="panel-agents">
                    <div className="list-header">Agents</div>
                    <div className="list-scroll">
                        {loading && (
                            <div className="placeholder-box" style={{ margin: 'var(--space-md)' }}>
                                Loading…
                            </div>
                        )}
                        {error && (
                            <div className="placeholder-box" style={{ margin: 'var(--space-md)', color: 'var(--color-error)' }}>
                                {error}
                            </div>
                        )}
                        {!loading && !error && agents.length === 0 && (
                            <div className="placeholder-box" style={{ margin: 'var(--space-md)' }}>
                                No agents
                            </div>
                        )}
                        {!loading && !error && agents.length > 0 && agents.map(agent => (
                            <NavLink
                                key={agent.id}
                                to={`/agents/${agent.id}/skills`}
                                className={({ isActive }) => `list-item ${isActive ? 'active' : ''}`}
                            >
                                <div className="list-item-title">{agent.name}</div>
                                <div className="list-item-desc">{agent.id}</div>
                            </NavLink>
                        ))}
                    </div>
                </aside>

                <div className="panel-gui">
                    <Outlet context={{ role: user?.role ?? 'viewer' }} />
                </div>

                {isEditor && (
                    <div className={`panel-lui ${luiHidden ? 'collapsed' : ''}`}>
                        <div className="lui-header">
                            <div className="lui-status-dot lui-status-dot-active" />
                            <strong style={{ fontSize: '13px', color: 'var(--color-text-primary)' }}>Meta-Agent</strong>
                            {selectedAgentId && (
                                <span style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginLeft: 'auto' }}>
                                    for {selectedAgentId}
                                </span>
                            )}
                            <button
                                type="button"
                                className="lui-toggle-btn"
                                style={{ marginLeft: selectedAgentId ? 'var(--space-xs)' : 'auto' }}
                                title="Hide Meta-Agent"
                                onClick={() => setLuiHidden(true)}
                            >
                                {'\u2715'}
                            </button>
                        </div>
                        <ChatPanel key="meta-agent-chat" agentId={selectedAgentId ?? 'meta_builder'} />
                    </div>
                )}
            </div>

            {isEditor && luiHidden && (
                <button
                    type="button"
                    className="lui-fab"
                    title="Show Meta-Agent"
                    onClick={() => setLuiHidden(false)}
                >
                    {'\uD83D\uDCAC'}
                </button>
            )}
        </div>
    )
}
