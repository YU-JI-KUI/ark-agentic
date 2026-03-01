import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type AgentMeta } from '../api'

export default function Dashboard() {
    const [agents, setAgents] = useState<AgentMeta[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const navigate = useNavigate()

    useEffect(() => {
        api.listAgents()
            .then(setAgents)
            .catch(e => setError(e.message))
            .finally(() => setLoading(false))
    }, [])

    if (loading) {
        return (
            <div className="loading">
                <div className="spinner" />
            </div>
        )
    }

    if (error) {
        return (
            <div className="page-container">
                <div className="empty-state">
                    <div className="empty-state-icon">⚠️</div>
                    <h3>Failed to load agents</h3>
                    <p>{error}</p>
                </div>
            </div>
        )
    }

    return (
        <div className="page-container">
            <div className="page-header">
                <h1>🏢 Ark-Agentic Studio</h1>
                <p>Manage your AI agents, skills, tools, and sessions</p>
            </div>

            {agents.length === 0 ? (
                <div className="empty-state">
                    <div className="empty-state-icon">🤖</div>
                    <h3>No agents found</h3>
                    <p>Create your first agent to get started</p>
                </div>
            ) : (
                <div className="agent-grid">
                    {agents.map(agent => (
                        <div
                            key={agent.id}
                            className="card agent-card"
                            onClick={() => navigate(`/agents/${agent.id}/skills`)}
                        >
                            <div className="agent-card-header">
                                <div className="agent-avatar">
                                    {agent.name.charAt(0).toUpperCase()}
                                </div>
                                <div>
                                    <div className="agent-card-title">{agent.name}</div>
                                    <div className="agent-card-id">{agent.id}</div>
                                </div>
                            </div>
                            <div className="agent-card-desc">
                                {agent.description || 'No description available'}
                            </div>
                            <div className="agent-card-footer">
                                <span className="status-badge">{agent.status || 'active'}</span>
                                <button
                                    className="btn btn-primary"
                                    onClick={e => {
                                        e.stopPropagation()
                                        navigate(`/agents/${agent.id}/skills`)
                                    }}
                                >
                                    Manage →
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
