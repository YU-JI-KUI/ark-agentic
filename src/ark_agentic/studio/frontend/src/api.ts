/* API client for Studio backend */

const API_BASE = '/api/studio'

export interface AgentMeta {
    id: string
    name: string
    description: string
    status: string
    created_at: string
    updated_at: string
}

export interface SkillMeta {
    id: string
    name: string
    description: string
    file_path: string
    content: string
}

export interface ToolMeta {
    name: string
    description: string
    group: string
    file_path: string
    parameters: Record<string, unknown>
}

export interface SessionItem {
    session_id: string
    message_count: number
    state: Record<string, unknown>
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
    const res = await fetch(url, init)
    if (!res.ok) {
        const detail = await res.text()
        throw new Error(`API Error ${res.status}: ${detail}`)
    }
    return res.json()
}

export const api = {
    // Agents
    listAgents: () =>
        fetchJSON<{ agents: AgentMeta[] }>(`${API_BASE}/agents`).then(r => r.agents),

    getAgent: (id: string) =>
        fetchJSON<AgentMeta>(`${API_BASE}/agents/${id}`),

    // Skills
    listSkills: (agentId: string) =>
        fetchJSON<{ skills: SkillMeta[] }>(`${API_BASE}/agents/${agentId}/skills`).then(r => r.skills),

    // Tools
    listTools: (agentId: string) =>
        fetchJSON<{ tools: ToolMeta[] }>(`${API_BASE}/agents/${agentId}/tools`).then(r => r.tools),

    // Sessions
    listSessions: (agentId: string) =>
        fetchJSON<{ sessions: SessionItem[] }>(`${API_BASE}/agents/${agentId}/sessions`).then(r => r.sessions),
}
