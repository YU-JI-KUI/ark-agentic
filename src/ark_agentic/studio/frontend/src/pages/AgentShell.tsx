import { useEffect, useState } from 'react'
import { Routes, Route, NavLink, useParams, useNavigate } from 'react-router-dom'
import { api, type AgentMeta } from '../api'
import SkillsView from './SkillsView'
import ToolsView from './ToolsView'
import SessionsView from './SessionsView'
import MemoryView from './MemoryView'
import ChatPanel from './ChatPanel'

export default function AgentShell() {
    const { agentId } = useParams<{ agentId: string }>()
    const navigate = useNavigate()
    const [agent, setAgent] = useState<AgentMeta | null>(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        if (!agentId) return
        api.getAgent(agentId)
            .then(setAgent)
            .catch(() => setAgent({ id: agentId, name: agentId, description: '', status: 'unknown', created_at: '', updated_at: '' }))
            .finally(() => setLoading(false))
    }, [agentId])

    if (loading || !agentId) {
        return <div className="loading"><div className="spinner" /></div>
    }

    return (
        <div className="agent-shell">
            {/* Top App Bar */}
            <div className="agent-topbar">
                <button className="back-btn" onClick={() => navigate('/')}>
                    ← Back to Console
                </button>
                <div className="agent-context-tag">
                    🤖 Target Agent: <span>{agent?.name || agentId}</span>
                </div>
            </div>

            {/* Main Split Layout: GUI (Left) + LUI (Right) */}
            <div className="main-layout">

                {/* Left GUI Panel */}
                <div className="panel-gui">
                    <nav className="gui-tabs">
                        <NavLink to={`/agents/${agentId}/skills`} className={({ isActive }) => isActive ? 'active' : ''}>
                            🧠 Skills
                        </NavLink>
                        <NavLink to={`/agents/${agentId}/tools`} className={({ isActive }) => isActive ? 'active' : ''}>
                            🛠️ Tools
                        </NavLink>
                        <NavLink to={`/agents/${agentId}/sessions`} className={({ isActive }) => isActive ? 'active' : ''}>
                            💬 Sessions
                        </NavLink>
                        <NavLink to={`/agents/${agentId}/memory`} className={({ isActive }) => isActive ? 'active' : ''}>
                            📚 Memory
                        </NavLink>
                    </nav>

                    <div className="gui-content">
                        <Routes>
                            <Route path="skills" element={<SkillsView agentId={agentId} />} />
                            <Route path="tools" element={<ToolsView agentId={agentId} />} />
                            <Route path="sessions" element={<SessionsView agentId={agentId} />} />
                            <Route path="memory" element={<MemoryView />} />
                        </Routes>
                    </div>
                </div>

                {/* Right LUI Panel — Meta-Agent Chat */}
                <div className="panel-lui">
                    <div className="lui-header">
                        <div className="lui-status-dot lui-status-dot-active"></div>
                        <strong style={{ fontSize: '13px', color: 'var(--color-text-primary)' }}>Meta-Agent</strong>
                        <span style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginLeft: 'auto' }}>对 {agentId}</span>
                    </div>
                    <ChatPanel agentId={agentId} />
                </div>

            </div>
        </div>
    )
}
