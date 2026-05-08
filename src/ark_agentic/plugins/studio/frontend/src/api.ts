/* API client for Studio backend */

import type { StudioRole } from './auth'

const API_BASE = '/api/studio'
const CHAT_URL = '/chat'

// ── Auth helpers ─────────────────────────────────────────────────

const AUTH_STORAGE_KEY = 'ark_studio_user'
const STUDIO_BASE_PATH = '/studio'
const STUDIO_LOGIN_PATH = `${STUDIO_BASE_PATH}/login`

function clearStoredAuth(): void {
    try {
        localStorage.removeItem(AUTH_STORAGE_KEY)
    } catch {
        // Ignore storage failures; the redirect still moves the user out of the protected app.
    }
}

function getStudioNextPath(): string {
    const { pathname, search, hash } = window.location
    let nextPath = pathname
    if (pathname === STUDIO_BASE_PATH) {
        nextPath = '/'
    } else if (pathname.startsWith(`${STUDIO_BASE_PATH}/`)) {
        nextPath = pathname.slice(STUDIO_BASE_PATH.length)
    }
    if (!nextPath.startsWith('/')) nextPath = `/${nextPath}`
    return `${nextPath}${search}${hash}`
}

function shouldRedirectToLogin(status: number, detail: string): boolean {
    return status === 401 || (status === 403 && detail.includes('Studio user is not authorized'))
}

function redirectToLogin(): void {
    if (window.location.pathname === STUDIO_LOGIN_PATH) return
    clearStoredAuth()
    const loginUrl = new URL(STUDIO_LOGIN_PATH, window.location.origin)
    const nextPath = getStudioNextPath()
    if (nextPath !== '/login') loginUrl.searchParams.set('next', nextPath)
    window.location.replace(`${loginUrl.pathname}${loginUrl.search}`)
}

export function getAuthUserId(): string | undefined {
    try {
        const raw = localStorage.getItem(AUTH_STORAGE_KEY)
        if (!raw) return undefined
        return JSON.parse(raw).user_id as string
    } catch {
        return undefined
    }
}

export function getAuthToken(): string | undefined {
    try {
        const raw = localStorage.getItem(AUTH_STORAGE_KEY)
        if (!raw) return undefined
        const token = JSON.parse(raw).token as string | undefined
        return token || undefined
    } catch {
        return undefined
    }
}

export function getAuthTokenId(): string | undefined {
    try {
        const raw = localStorage.getItem(AUTH_STORAGE_KEY)
        if (!raw) return undefined
        const tokenId = JSON.parse(raw).token_id as string | undefined
        return tokenId || undefined
    } catch {
        return undefined
    }
}

function withAuth(init: RequestInit = {}): RequestInit {
    const headers = new Headers(init.headers)
    const token = getAuthToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    return { ...init, headers }
}

function withTokenId(init: RequestInit = {}): RequestInit {
    const headers = new Headers(init.headers)
    const tokenId = getAuthTokenId()
    if (tokenId) headers.set('X-Token-ID', tokenId)
    return { ...init, headers }
}

// ── Chat / SSE Streaming ──────────────────────────────────────────

export interface ChatRequest {
    agent_id: string
    message: string
    session_id?: string
    stream?: boolean
    protocol?: string
    context?: Record<string, string>
    user_id?: string
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
    const userId = req.user_id || getAuthUserId()
    const body = { ...req, stream: true, protocol: 'agui', user_id: userId }
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (userId) headers['x-ark-user-id'] = userId
    const response = await fetch(CHAT_URL, {
        method: 'POST',
        headers,
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
    modified_at?: string | null
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
    modified_at?: string | null
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

export interface TurnContext {
    active_skill_id: string | null
    tools_mounted: string[]
}

export interface MessageItem {
    role: string
    content: string | null
    tool_calls?: Array<{ id: string; name: string; arguments: Record<string, unknown> }> | null
    tool_results?: Array<{
        tool_call_id: string
        content: unknown
        is_error?: boolean
        result_type?: string
        llm_digest?: string | null
        metadata?: Record<string, unknown> | null
    }> | null
    thinking?: string | null
    metadata?: Record<string, unknown> | null
    finish_reason?: string | null
    turn_context?: TurnContext | null
}

export interface MemoryFileItem {
    user_id: string
    file_path: string
    file_type: string
    size_bytes: number
    modified_at: string | null
}

export interface StudioUserGrant {
    user_id: string
    role: StudioRole
    created_at: string
    updated_at: string
    created_by?: string | null
    updated_by?: string | null
}

export interface StudioUsersPage {
    users: StudioUserGrant[]
    total: number
    admin_count: number
    limit: number
    offset: number
}

export interface SessionDetail {
    session_id: string
    message_count: number
    state: Record<string, unknown>
    messages: MessageItem[]
}

export interface TraceLinkConfig {
    enabled: boolean
    template: string | null
}

export interface StudioFeaturesConfig {
    mcp_enabled: boolean
}

export interface MCPToolMeta {
    name: string
    registered_name: string
    description: string
    enabled: boolean
    input_schema: Record<string, unknown>
    parameter_count: number
}

export interface MCPServerMeta {
    id: string
    name: string
    description: string
    transport: string
    enabled: boolean
    required: boolean
    timeout: number
    url?: string | null
    command?: string | null
    args: string[]
    env: Record<string, string>
    headers: Record<string, string>
    status: string
    error?: string | null
    total_tools: number
    enabled_tools: number
    tools: MCPToolMeta[]
}

// ── Dashboard summary ─────────────────────────────────────────────

export interface DashboardTrendPoint {
    label: string
    short_label: string
    value: number
}

export interface DashboardDistributionItem {
    label: string
    value: number
    hint: string | null
}

export interface DashboardInsightStat {
    label: string
    value: string
    hint: string | null
}

export interface DashboardActivityItem {
    ts: string
    kind: 'skill' | 'tool' | 'session' | 'memory'
    agent: string
    agent_label: string
    text: string
    status: 'ok' | 'warn' | 'error'
}

export interface DashboardSummaryResponse {
    total_agents: number
    total_users: number
    total_skills: number
    total_tools: number
    total_sessions: number
    total_memory_files: number
    total_memory_bytes: number
    trends: {
        users: DashboardTrendPoint[]
        skills: DashboardTrendPoint[]
        tools: DashboardTrendPoint[]
        sessions: DashboardTrendPoint[]
        memory: DashboardTrendPoint[]
    }
    skills: {
        stats: DashboardInsightStat[]
        groups: DashboardDistributionItem[]
        tags: DashboardDistributionItem[]
    }
    tools: {
        stats: DashboardInsightStat[]
        groups: DashboardDistributionItem[]
        agents: DashboardDistributionItem[]
    }
    sessions: {
        stats: DashboardInsightStat[]
        agents: DashboardDistributionItem[]
        message_bands: DashboardDistributionItem[]
    }
    memory: {
        stats: DashboardInsightStat[]
        file_types: DashboardDistributionItem[]
        agents: DashboardDistributionItem[]
    }
    activity: DashboardActivityItem[]
    generated_at: string
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

export interface MCPServerCreateInput {
    id: string
    name?: string
    description?: string
    transport: 'stdio' | 'streamable_http'
    enabled?: boolean
    required?: boolean
    timeout?: number
    url?: string
    command?: string
    args?: string[] | string
    env?: Record<string, string>
    headers?: Record<string, string>
}

export type MCPServerUpdateInput = Omit<MCPServerCreateInput, 'id'>

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
    const res = await fetch(url, withAuth(init))
    if (!res.ok) {
        await raiseAPIError(res)
    }
    return res.json()
}

async function raiseAPIError(res: Response): Promise<never> {
    const detail = await res.text()
    if (shouldRedirectToLogin(res.status, detail)) {
        redirectToLogin()
    }
    throw new Error(`API Error ${res.status}: ${detail}`)
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export const api = {
    // Auth
    logout: () =>
        fetchJSON<{ status: string; result: boolean | null }>(
            `${API_BASE}/auth/logout`,
            withTokenId({ method: 'POST' }),
        ),

    // Users
    listUsers: (params: { query?: string; role?: StudioRole | 'all'; limit?: number; offset?: number } = {}) => {
        const search = new URLSearchParams()
        if (params.query?.trim()) search.set('query', params.query.trim())
        if (params.role && params.role !== 'all') search.set('role', params.role)
        if (params.limit) search.set('limit', String(params.limit))
        if (params.offset) search.set('offset', String(params.offset))
        const suffix = search.toString() ? `?${search.toString()}` : ''
        return fetchJSON<StudioUsersPage>(`${API_BASE}/users${suffix}`)
    },

    saveUserGrant: (data: { user_id: string; role: StudioRole }) =>
        fetchJSON<StudioUserGrant>(`${API_BASE}/users`, {
            method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(data),
        }),

    deleteUserGrant: (userId: string) =>
        fetchJSON<{ status: string; user_id: string }>(`${API_BASE}/users/${encodeURIComponent(userId)}`, {
            method: 'DELETE',
        }),

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
        const res = await fetch(
            `${API_BASE}/agents/${agentId}/sessions/${sessionId}/raw?user_id=${encodeURIComponent(userId)}`,
            withAuth(),
        )
        if (!res.ok) {
            await raiseAPIError(res)
        }
        return res.text()
    },

    putSessionRaw: (agentId: string, sessionId: string, userId: string, body: string) =>
        fetch(`${API_BASE}/agents/${agentId}/sessions/${sessionId}/raw?user_id=${encodeURIComponent(userId)}`, withAuth({
            method: 'PUT',
            headers: { 'Content-Type': 'text/plain' },
            body,
        })).then(async res => {
            if (!res.ok) {
                await raiseAPIError(res)
            }
            return res.json() as Promise<{ status: string; session_id: string }>
        }),

    // Config
    getTraceLinkConfig: () =>
        fetchJSON<TraceLinkConfig>(`${API_BASE}/config/trace-link`),

    getStudioFeaturesConfig: () =>
        fetchJSON<StudioFeaturesConfig>(`${API_BASE}/config/features`),

    // Memory
    listMemoryFiles: (agentId: string) =>
        fetchJSON<{ files: MemoryFileItem[] }>(`${API_BASE}/agents/${agentId}/memory/files`).then(r => r.files),

    getMemoryContent: async (agentId: string, filePath: string, userId: string): Promise<string> => {
        const res = await fetch(
            `${API_BASE}/agents/${agentId}/memory/content?file_path=${encodeURIComponent(filePath)}&user_id=${encodeURIComponent(userId)}`,
            withAuth(),
        )
        if (!res.ok) {
            await raiseAPIError(res)
        }
        return res.text()
    },

    putMemoryContent: async (agentId: string, filePath: string, userId: string, body: string): Promise<{ status: string }> => {
        const res = await fetch(
            `${API_BASE}/agents/${agentId}/memory/content?file_path=${encodeURIComponent(filePath)}&user_id=${encodeURIComponent(userId)}`,
            withAuth({ method: 'PUT', headers: { 'Content-Type': 'text/plain' }, body }),
        )
        if (!res.ok) {
            await raiseAPIError(res)
        }
        return res.json()
    },

    // MCP
    listMCPServers: (agentId: string) =>
        fetchJSON<{ servers: MCPServerMeta[] }>(`${API_BASE}/agents/${agentId}/mcp`).then(r => r.servers),

    createMCPServer: (agentId: string, data: MCPServerCreateInput) =>
        fetchJSON<MCPServerMeta>(`${API_BASE}/agents/${agentId}/mcp/servers`, {
            method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(data),
        }),

    updateMCPServer: (agentId: string, serverId: string, enabled: boolean) =>
        fetchJSON<MCPServerMeta>(
            `${API_BASE}/agents/${agentId}/mcp/servers/${encodeURIComponent(serverId)}`,
            { method: 'PATCH', headers: JSON_HEADERS, body: JSON.stringify({ enabled }) },
        ),

    replaceMCPServer: (agentId: string, serverId: string, data: MCPServerUpdateInput) =>
        fetchJSON<MCPServerMeta>(
            `${API_BASE}/agents/${agentId}/mcp/servers/${encodeURIComponent(serverId)}`,
            { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify(data) },
        ),

    deleteMCPServer: (agentId: string, serverId: string) =>
        fetchJSON<{ status: string; server_id: string }>(
            `${API_BASE}/agents/${agentId}/mcp/servers/${encodeURIComponent(serverId)}`,
            { method: 'DELETE' },
        ),

    updateMCPTool: (agentId: string, serverId: string, toolName: string, enabled: boolean) =>
        fetchJSON<MCPServerMeta>(
            `${API_BASE}/agents/${agentId}/mcp/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(toolName)}`,
            { method: 'PATCH', headers: JSON_HEADERS, body: JSON.stringify({ enabled }) },
        ),

    // Dashboard
    getDashboardSummary: () =>
        fetchJSON<DashboardSummaryResponse>(`${API_BASE}/dashboard/summary`),
}
