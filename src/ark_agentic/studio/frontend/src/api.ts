/* API client for Studio backend */

const API_BASE = '/api/studio'
const CHAT_URL = '/chat'

// ── Chat / SSE Streaming ──────────────────────────────────────────

export interface ChatRequest {
    agent_id: string
    message: string
    session_id?: string
    stream?: boolean
    protocol?: string
    context?: Record<string, string>
}

export interface AgentStreamEvent {
    type: string
    seq: number
    run_id: string
    session_id: string
    // text
    delta?: string
    message_id?: string
    turn?: number
    content_kind?: 'text' | 'a2ui'
    // tool_call
    tool_call_id?: string
    tool_name?: string
    tool_args?: Record<string, unknown>
    tool_result?: unknown
    // step
    step_name?: string
    // life-cycle
    run_content?: string
    message?: string
    error_message?: string
}

/**
 * Open a streaming chat connection to /chat.
 * Returns an async generator of parsed AgentStreamEvent objects.
 */
export async function* streamChat(req: ChatRequest): AsyncGenerator<AgentStreamEvent> {
    const body: ChatRequest = { ...req, stream: true, protocol: 'agui' }
    const response = await fetch(CHAT_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    })
    if (!response.ok || !response.body) {
        const detail = await response.text()
        throw new Error(`Chat API Error ${response.status}: ${detail}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''   // keep partial last line
        for (const line of lines) {
            if (line.startsWith('data: ')) {
                const data = line.slice(6).trim()
                if (data && data !== '[DONE]') {
                    try {
                        yield JSON.parse(data) as AgentStreamEvent
                    } catch {
                        // skip non-JSON lines
                    }
                }
            }
        }
    }
}


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
    user_id: string
    message_count: number
    state: Record<string, unknown>
    created_at: string | null
    updated_at: string | null
    first_message: string | null
}

export interface MessageItem {
    role: string
    content: string | null
    tool_calls?: Array<{ id: string; name: string; arguments: Record<string, unknown> }> | null
    tool_results?: Array<{ tool_call_id: string; content: unknown; is_error?: boolean }> | null
    thinking?: string | null
    metadata?: Record<string, unknown> | null
}

export interface MemoryFileItem {
    user_id: string
    file_path: string
    file_type: string
    size_bytes: number
    modified_at: string | null
}

export interface SessionDetail {
    session_id: string
    message_count: number
    state: Record<string, unknown>
    messages: MessageItem[]
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

    // Sessions (view + edit only; no create/delete)
    listSessions: (agentId: string) =>
        fetchJSON<{ sessions: SessionItem[] }>(`${API_BASE}/agents/${agentId}/sessions`).then(r => r.sessions),

    getSessionDetail: (agentId: string, sessionId: string, userId: string) =>
        fetchJSON<SessionDetail>(`${API_BASE}/agents/${agentId}/sessions/${sessionId}?user_id=${encodeURIComponent(userId)}`),

    getSessionRaw: async (agentId: string, sessionId: string, userId: string): Promise<string> => {
        const res = await fetch(`${API_BASE}/agents/${agentId}/sessions/${sessionId}/raw?user_id=${encodeURIComponent(userId)}`)
        if (!res.ok) {
            const t = await res.text()
            throw new Error(`API Error ${res.status}: ${t}`)
        }
        return res.text()
    },

    putSessionRaw: (agentId: string, sessionId: string, userId: string, body: string) =>
        fetch(`${API_BASE}/agents/${agentId}/sessions/${sessionId}/raw?user_id=${encodeURIComponent(userId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'text/plain' },
            body,
        }).then(async res => {
            if (!res.ok) {
                const t = await res.text()
                throw new Error(`API Error ${res.status}: ${t}`)
            }
            return res.json() as Promise<{ status: string; session_id: string }>
        }),

    // Memory
    listMemoryFiles: (agentId: string) =>
        fetchJSON<{ files: MemoryFileItem[] }>(`${API_BASE}/agents/${agentId}/memory/files`).then(r => r.files),

    getMemoryContent: async (agentId: string, filePath: string, userId: string): Promise<string> => {
        const res = await fetch(
            `${API_BASE}/agents/${agentId}/memory/content?file_path=${encodeURIComponent(filePath)}&user_id=${encodeURIComponent(userId)}`
        )
        if (!res.ok) {
            const t = await res.text()
            throw new Error(`API Error ${res.status}: ${t}`)
        }
        return res.text()
    },

    putMemoryContent: async (agentId: string, filePath: string, userId: string, body: string): Promise<{ status: string }> => {
        const res = await fetch(
            `${API_BASE}/agents/${agentId}/memory/content?file_path=${encodeURIComponent(filePath)}&user_id=${encodeURIComponent(userId)}`,
            { method: 'PUT', headers: { 'Content-Type': 'text/plain' }, body },
        )
        if (!res.ok) {
            const t = await res.text()
            throw new Error(`API Error ${res.status}: ${t}`)
        }
        return res.json()
    },
}

