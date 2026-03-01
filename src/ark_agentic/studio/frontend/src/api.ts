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
    version?: string
    invocation_policy?: string
    group?: string
    tags?: string[]
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

// ── Mutation Input Types ───────────────────────────────────────────

export interface SkillCreateInput {
    name: string
    description?: string
    content?: string
}

export interface SkillUpdateInput {
    name?: string
    description?: string
    content?: string
}

export interface ToolScaffoldInput {
    name: string
    description?: string
    parameters?: { name: string; description?: string; type?: string; required?: boolean }[]
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
    const res = await fetch(url, init)
    if (!res.ok) {
        const detail = await res.text()
        throw new Error(`API Error ${res.status}: ${detail}`)
    }
    return res.json()
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export const api = {
    // Agents
    listAgents: () =>
        fetchJSON<{ agents: AgentMeta[] }>(`${API_BASE}/agents`).then(r => r.agents),

    getAgent: (id: string) =>
        fetchJSON<AgentMeta>(`${API_BASE}/agents/${id}`),

    // Skills - Read
    listSkills: (agentId: string) =>
        fetchJSON<{ skills: SkillMeta[] }>(`${API_BASE}/agents/${agentId}/skills`).then(r => r.skills),

    // Skills - Mutations
    createSkill: (agentId: string, data: SkillCreateInput) =>
        fetchJSON<SkillMeta>(`${API_BASE}/agents/${agentId}/skills`, {
            method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(data),
        }),

    updateSkill: (agentId: string, skillId: string, data: SkillUpdateInput) =>
        fetchJSON<SkillMeta>(`${API_BASE}/agents/${agentId}/skills/${skillId}`, {
            method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify(data),
        }),

    deleteSkill: (agentId: string, skillId: string) =>
        fetchJSON<{ status: string }>(`${API_BASE}/agents/${agentId}/skills/${skillId}`, {
            method: 'DELETE',
        }),

    // Tools - Read
    listTools: (agentId: string) =>
        fetchJSON<{ tools: ToolMeta[] }>(`${API_BASE}/agents/${agentId}/tools`).then(r => r.tools),

    // Tools - Scaffold
    scaffoldTool: (agentId: string, data: ToolScaffoldInput) =>
        fetchJSON<ToolMeta>(`${API_BASE}/agents/${agentId}/tools`, {
            method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(data),
        }),

    // Sessions
    listSessions: (agentId: string) =>
        fetchJSON<{ sessions: SessionItem[] }>(`${API_BASE}/agents/${agentId}/sessions`).then(r => r.sessions),
}

