import { useEffect, useState } from 'react'
import { NavLink, useParams, useOutletContext, Outlet, Navigate } from 'react-router-dom'
import { api, type AgentMeta } from '../api'
import SkillsView from './SkillsView'
import ToolsView from './ToolsView'
import SessionsView from './SessionsView'
import MemoryView from './MemoryView'

export function SkillsViewTab() {
    const { agentId } = useOutletContext<{ agentId: string }>()
    return <SkillsView agentId={agentId} />
}

export function ToolsViewTab() {
    const { agentId } = useOutletContext<{ agentId: string }>()
    return <ToolsView agentId={agentId} />
}

export function SessionsViewTab() {
    const { agentId } = useOutletContext<{ agentId: string }>()
    return <SessionsView agentId={agentId} />
}

export function MemoryViewTab() {
    return <MemoryView />
}

export default function AgentDetail() {
    const { agentId } = useParams<{ agentId: string }>()
    const [_agent, setAgent] = useState<AgentMeta | null>(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        if (!agentId) return
        api.getAgent(agentId)
            .then(setAgent)
            .catch(() => setAgent({ id: agentId, name: agentId, description: '', status: 'unknown', created_at: '', updated_at: '' }))
            .finally(() => setLoading(false))
    }, [agentId])

    if (!agentId) {
        return <Navigate to="/" replace />
    }

    if (loading) {
        return (
            <div className="gui-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 200 }}>
                <div className="loading"><div className="spinner" /></div>
            </div>
        )
    }

    return (
        <>
            <nav className="gui-tabs">
                <NavLink to={`/agents/${agentId}/skills`} className={({ isActive }) => isActive ? 'active' : ''}>
                    Skills
                </NavLink>
                <NavLink to={`/agents/${agentId}/tools`} className={({ isActive }) => isActive ? 'active' : ''}>
                    Tools
                </NavLink>
                <NavLink to={`/agents/${agentId}/sessions`} className={({ isActive }) => isActive ? 'active' : ''}>
                    Sessions
                </NavLink>
                <NavLink to={`/agents/${agentId}/memory`} className={({ isActive }) => isActive ? 'active' : ''}>
                    Memory
                </NavLink>
            </nav>

            <div className="gui-content">
                <Outlet context={{ agentId }} />
            </div>
        </>
    )
}
