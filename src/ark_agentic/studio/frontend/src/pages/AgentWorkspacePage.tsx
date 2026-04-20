import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type WheelEvent as ReactWheelEvent,
} from 'react'
import { NavLink, Navigate, useNavigate, useOutletContext, useParams, useSearchParams } from 'react-router-dom'
import {
  api,
  type MemoryFileItem,
  type MessageItem,
  type SessionDetail,
  type SessionItem,
  type SkillMeta,
  type ToolMeta,
} from '../api'
import { useAuth } from '../auth'
import type { StudioShellContextValue } from '../layouts/StudioShell'
import { ChevronRightIcon, CollapseIcon, CopyIcon, ExpandIcon, PlusIcon } from '../components/StudioIcons'

const VALID_SECTIONS = new Set(['overview', 'skills', 'tools', 'sessions', 'memory'])

function formatRelativeTime(value: string | null) {
  if (!value) return 'unknown'
  const diff = Date.now() - new Date(value).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function formatAgentDate(value: string | null | undefined) {
  if (!value) return 'updated unknown'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'updated unknown'
  return `updated ${parsed.toLocaleDateString()}`
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '—'
  return parsed.toLocaleString('zh-CN', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function toDomId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]+/g, '-')
}

function getTimestampValue(value: string | null | undefined) {
  if (!value) return 0
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? 0 : timestamp
}

function executionLaneLabel(lane: TraceLane) {
  switch (lane) {
    case 'input':
      return 'Input'
    case 'reasoning':
      return 'Reasoning'
    case 'tools':
      return 'Tools'
    case 'output':
      return 'Output'
    case 'metadata':
      return 'Metadata'
  }
}

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = value
  textarea.setAttribute('readonly', 'true')
  textarea.style.position = 'absolute'
  textarea.style.left = '-9999px'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  document.body.removeChild(textarea)
}

function StructuredDataPanel({
  title,
  value,
  emptyText,
  compact = false,
  headingId,
  headingLevel = 'h3',
  showTitle = true,
}: {
  title: string
  value: string | null | undefined
  emptyText: string
  compact?: boolean
  headingId?: string
  headingLevel?: 'h3' | 'h4'
  showTitle?: boolean
}) {
  const content = value && value.trim() ? value : emptyText
  const HeadingTag = headingLevel

  return (
    <section className={`structured-data-panel ${compact ? 'structured-data-panel-compact' : ''}`}>
      {showTitle && (
        <div className="structured-data-panel-head">
          <HeadingTag id={headingId}>{title}</HeadingTag>
        </div>
      )}
      <div className="code-block-shell expanded">
        <pre className={`code-block ${compact ? 'compact' : ''}`}>{content}</pre>
      </div>
    </section>
  )
}

function StructuredDataControls({
  copied,
  expanded,
  extraActions,
  title,
  onCopy,
  onToggle,
}: {
  copied: boolean
  expanded: boolean
  extraActions?: ReactNode
  title: string
  onCopy: () => void
  onToggle: () => void
}) {
  return (
    <div className="structured-data-actions">
      {extraActions}
      <span className={`structured-data-copy-status ${copied ? 'visible' : ''}`} role="status">
        Copied
      </span>
      <button
        aria-label={copied ? `${title} copied` : `Copy ${title}`}
        className="icon-action-button"
        onClick={onCopy}
        type="button"
      >
        <CopyIcon />
      </button>
      <button
        aria-label={expanded ? `Collapse ${title}` : `Expand ${title}`}
        className="icon-action-button"
        onClick={onToggle}
        type="button"
      >
        {expanded ? <CollapseIcon /> : <ExpandIcon />}
      </button>
    </div>
  )
}

function StructuredDataCard({
  title,
  value,
  emptyText,
  extraActions,
  compact = false,
  headingId,
  headingLevel = 'h3',
  expandedOverride,
}: {
  title: string
  value: string | null | undefined
  emptyText: string
  extraActions?: ReactNode
  compact?: boolean
  headingId?: string
  headingLevel?: 'h3' | 'h4'
  expandedOverride?: boolean
}) {
  const [expanded, setExpanded] = useState(expandedOverride ?? false)
  const [copied, setCopied] = useState(false)
  const content = value && value.trim() ? value : emptyText
  const HeadingTag = headingLevel

  useEffect(() => {
    if (expandedOverride === undefined) return
    setExpanded(expandedOverride)
  }, [expandedOverride])

  async function handleCopy() {
    try {
      await copyText(content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      setCopied(false)
    }
  }

  return (
    <section className={`content-card detail-data-card ${compact ? 'detail-data-card-compact' : ''}`}>
      <div className="detail-data-card-head">
        <HeadingTag id={headingId}>{title}</HeadingTag>
        <div className="detail-data-card-head-actions">
          <StructuredDataControls
            copied={copied}
            expanded={expanded}
            extraActions={extraActions}
            onCopy={() => void handleCopy()}
            onToggle={() => setExpanded(current => !current)}
            title={title}
          />
        </div>
      </div>
      {expanded && (
        <StructuredDataPanel
          compact={compact}
          emptyText={emptyText}
          showTitle={false}
          title={title}
          value={value}
        />
      )}
      <div aria-live="polite" className="sr-only">
        {copied ? `${title} copied` : ''}
      </div>
    </section>
  )
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function truncate(value: string | null | undefined, max = 120) {
  if (!value) return 'No content'
  return value.length > max ? `${value.slice(0, max)}…` : value
}

function analyzeToolReliability(tools: ToolMeta[]) {
  if (tools.length === 0) {
    return { score: 0, documented: 0, typed: 0, label: 'No tools' }
  }

  const documented = tools.filter(tool => Boolean(tool.description?.trim())).length
  const typed = tools.filter(tool => Object.keys(tool.parameters || {}).length > 0).length
  const score = Math.round(((documented + typed) / (tools.length * 2)) * 100)
  const label =
    score >= 80 ? 'Strong signal'
    : score >= 50 ? 'Mixed signal'
    : 'Weak signal'

  return { score, documented, typed, label }
}

type TraceEvent = {
  kind: 'user' | 'assistant' | 'thinking' | 'tool_call' | 'tool_result' | 'metadata'
  label: string
  preview: string
}

type TraceLane = 'input' | 'reasoning' | 'tools' | 'output' | 'metadata'
const TRACE_LANES: TraceLane[] = ['input', 'reasoning', 'tools', 'output', 'metadata']

type TraceStage = {
  lane: TraceLane
  kind: TraceEvent['kind']
  label: string
  preview: string
  accent?: string
}

type ExecutionRound = {
  round: number
  stages: TraceStage[]
  userPrompt: string | null
  assistantOutput: string | null
  toolCallCount: number
  toolResultCount: number
  toolErrorCount: number
  reasoningCount: number
}

type ExecutionSummary = {
  roundCount: number
  toolCallCount: number
  toolResultCount: number
  toolErrorCount: number
  reasoningCount: number
}

function laneForEvent(kind: TraceEvent['kind']): TraceLane {
  switch (kind) {
    case 'user':
      return 'input'
    case 'thinking':
      return 'reasoning'
    case 'tool_call':
    case 'tool_result':
      return 'tools'
    case 'metadata':
      return 'metadata'
    case 'assistant':
    default:
      return 'output'
  }
}

function createExecutionRound(round: number): ExecutionRound {
  return {
    round,
    stages: [],
    userPrompt: null,
    assistantOutput: null,
    toolCallCount: 0,
    toolResultCount: 0,
    toolErrorCount: 0,
    reasoningCount: 0,
  }
}

function buildExecutionRounds(detail: SessionDetail | null): ExecutionRound[] {
  if (!detail) return []

  const rounds: ExecutionRound[] = []
  let currentRound: ExecutionRound | null = null

  function ensureTurn() {
    if (!currentRound) {
      currentRound = createExecutionRound(rounds.length + 1)
      rounds.push(currentRound)
    }
    return currentRound
  }

  function pushStage(kind: TraceEvent['kind'], label: string, preview: string, accent?: string) {
    const round = ensureTurn()
    round.stages.push({
      lane: laneForEvent(kind),
      kind,
      label,
      preview,
      accent,
    })
  }

  for (const message of detail.messages) {
    if (message.role === 'user' && (message.content || message.tool_calls?.length || message.tool_results?.length)) {
      currentRound = createExecutionRound(rounds.length + 1)
      rounds.push(currentRound)
    }

    if (message.content) {
      const round = ensureTurn()
      if (message.role === 'user') {
        round.userPrompt ??= truncate(message.content, 180)
      } else if (message.role === 'assistant') {
        round.assistantOutput = truncate(message.content, 180)
      }
      pushStage(
        message.role === 'user' ? 'user' : 'assistant',
        message.role === 'user' ? 'User Prompt' : 'Assistant Output',
        truncate(message.content, 180),
      )
    }

    if (message.thinking) {
      ensureTurn().reasoningCount += 1
      pushStage('thinking', 'Reasoning', truncate(message.thinking, 180))
    }

    for (const toolCall of message.tool_calls ?? []) {
      ensureTurn().toolCallCount += 1
      pushStage(
        'tool_call',
        `Tool Call · ${toolCall.name}`,
        truncate(JSON.stringify(toolCall.arguments), 180),
        'args',
      )
    }

    for (const toolResult of message.tool_results ?? []) {
      const round = ensureTurn()
      round.toolResultCount += 1
      if (toolResult.is_error) round.toolErrorCount += 1
      pushStage(
        'tool_result',
        `Tool Result · ${toolResult.tool_call_id}`,
        truncate(JSON.stringify(toolResult.content), 180),
        toolResult.is_error ? 'error' : 'result',
      )
    }

    if (message.metadata && Object.keys(message.metadata).length > 0) {
      pushStage('metadata', 'Metadata', truncate(JSON.stringify(message.metadata), 180))
    }
  }

  return rounds
}

function summarizeExecutionRounds(rounds: ExecutionRound[]): ExecutionSummary {
  return rounds.reduce<ExecutionSummary>(
    (summary, round) => ({
      roundCount: summary.roundCount + 1,
      toolCallCount: summary.toolCallCount + round.toolCallCount,
      toolResultCount: summary.toolResultCount + round.toolResultCount,
      toolErrorCount: summary.toolErrorCount + round.toolErrorCount,
      reasoningCount: summary.reasoningCount + round.reasoningCount,
    }),
    {
      roundCount: 0,
      toolCallCount: 0,
      toolResultCount: 0,
      toolErrorCount: 0,
      reasoningCount: 0,
    },
  )
}

type ViewMode = 'view' | 'create' | 'edit' | 'scaffold'

export default function AgentWorkspacePage() {
  const { agentId, section } = useParams<{ agentId: string; section: string }>()
  const { activeSection, selectedAgent } = useOutletContext<StudioShellContextValue>()
  const navigate = useNavigate()

  if (!agentId || !section || !VALID_SECTIONS.has(section)) {
    return <Navigate replace to={agentId ? `/agents/${agentId}/overview` : '/'} />
  }

  function focusSection(targetSection: string) {
    if (targetSection === activeSection) return
    void navigate(`/agents/${agentId}/${targetSection}`)
  }

  const isSplitSection = activeSection === 'skills' || activeSection === 'tools' || activeSection === 'sessions' || activeSection === 'memory'

  return (
    <div className={`workspace-page ${isSplitSection ? 'workspace-page-split' : ''}`}>
      <div aria-atomic="true" aria-live="polite" className="sr-only">
        {selectedAgent ? `${selectedAgent.name}, ${activeSection} section` : 'No agent selected'}
      </div>
      <section className="workspace-context-bar">
        <div className="workspace-context-head">
          <div className="workspace-context-copy">
            <h1>{selectedAgent?.name ?? agentId}</h1>
            {selectedAgent?.description && <p>{selectedAgent.description}</p>}
          </div>
          <div className="workspace-context-meta">
            <span>{selectedAgent?.id ?? agentId}</span>
            <span>{formatAgentDate(selectedAgent?.updated_at)}</span>
          </div>
        </div>

        <nav aria-label="Agent sections" className="workspace-tab-row">
          {['overview', 'skills', 'tools', 'sessions', 'memory'].map(item => (
            <NavLink
              aria-label={`${item} section`}
              className={({ isActive }) => `workspace-tab ${isActive ? 'active' : ''}`}
              key={item}
              onFocus={() => focusSection(item)}
              to={`/agents/${agentId}/${item}`}
            >
              {item}
            </NavLink>
          ))}
        </nav>
      </section>

      {activeSection === 'overview' && <OverviewSection agentId={agentId} />}
      {activeSection === 'skills' && <SkillsSection agentId={agentId} />}
      {activeSection === 'tools' && <ToolsSection agentId={agentId} />}
      {activeSection === 'sessions' && <SessionsSection agentId={agentId} />}
      {activeSection === 'memory' && <MemorySection agentId={agentId} />}
    </div>
  )
}

function OverviewSection({ agentId }: { agentId: string }) {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [snapshot, setSnapshot] = useState({
    skills: [] as SkillMeta[],
    tools: [] as ToolMeta[],
    sessions: [] as SessionItem[],
    files: [] as MemoryFileItem[],
  })

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [skills, tools, sessions, files] = await Promise.all([
          api.listSkills(agentId),
          api.listTools(agentId),
          api.listSessions(agentId),
          api.listMemoryFiles(agentId),
        ])
        if (!cancelled) {
          setSnapshot({ skills, tools, sessions, files })
        }
      } catch (nextError) {
        if (!cancelled) {
          setError(nextError instanceof Error ? nextError.message : String(nextError))
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [agentId])

  if (loading) {
    return <div className="empty-surface">Loading overview...</div>
  }
  if (error) {
    return <div className="empty-surface">{error}</div>
  }

  const reliability = analyzeToolReliability(snapshot.tools)
  const recentSkills = [...snapshot.skills]
    .sort((left, right) => getTimestampValue(right.modified_at) - getTimestampValue(left.modified_at))
    .slice(0, 3)
  const recentTools = [...snapshot.tools]
    .sort((left, right) => getTimestampValue(right.modified_at) - getTimestampValue(left.modified_at))
    .slice(0, 3)
  const recentFiles = [...snapshot.files]
    .sort((left, right) => getTimestampValue(right.modified_at) - getTimestampValue(left.modified_at))
    .slice(0, 3)
  const skillDescribedCount = snapshot.skills.filter(skill => Boolean(skill.description?.trim())).length
  const skillTaggedCount = snapshot.skills.filter(
    skill =>
      Boolean(skill.group?.trim()) ||
      Boolean(skill.invocation_policy?.trim()) ||
      Boolean(skill.tags?.length),
  ).length

  function openSkillDetail(skillId: string) {
    void navigate(`/agents/${agentId}/skills?skill=${encodeURIComponent(skillId)}`)
  }

  function openToolDetail(toolName: string) {
    void navigate(`/agents/${agentId}/tools?tool=${encodeURIComponent(toolName)}`)
  }

  function openMemoryDetail(filePath: string, userId: string) {
    void navigate(
      `/agents/${agentId}/memory?memory=${encodeURIComponent(filePath)}&user=${encodeURIComponent(userId)}`,
    )
  }

  return (
    <>
      <section className="workspace-grid-four overview-metric-grid">
        <div className="metric-surface metric-surface-compact">
          <div className="metric-surface-compact-copy">
            <span>Skills</span>
            <p>当前 Agent 已注册的技能条目。</p>
          </div>
          <strong>{snapshot.skills.length}</strong>
        </div>
        <div className="metric-surface metric-surface-compact">
          <div className="metric-surface-compact-copy">
            <span>Tools</span>
            <p>可被编排或调用的工具数量。</p>
          </div>
          <strong>{snapshot.tools.length}</strong>
        </div>
        <div className="metric-surface metric-surface-compact">
          <div className="metric-surface-compact-copy">
            <span>Sessions</span>
            <p>最近保留下来的会话记录总数。</p>
          </div>
          <strong>{snapshot.sessions.length}</strong>
        </div>
        <div className="metric-surface metric-surface-compact">
          <div className="metric-surface-compact-copy">
            <span>Memory Files</span>
            <p>当前 Agent 可见的 Memory 文件数量。</p>
          </div>
          <strong>{snapshot.files.length}</strong>
        </div>
      </section>

      <section className="workspace-grid-two">
        <article className="workspace-surface">
          <div className="surface-heading">
            <span>运行快照</span>
          </div>
          <div className="signal-list">
            <div className="signal-card">
              <strong>最近会话活动</strong>
              <p>
                {snapshot.sessions[0]
                  ? `${snapshot.sessions[0].user_id} · ${formatRelativeTime(snapshot.sessions[0].updated_at || snapshot.sessions[0].created_at)}`
                  : '暂无会话活动。'}
              </p>
            </div>
            <div className="signal-card">
              <strong>知识足迹</strong>
              <p>当前 Agent 可见 {snapshot.files.length} 个 MEMORY 文件。</p>
            </div>
          </div>
        </article>

        <article className="workspace-surface">
          <div className="surface-heading">
            <span>编辑视角</span>
          </div>
          <div className="signal-list">
            <div className="signal-card">
              <strong>SKILLS 完整性信号</strong>
              <p>
                {skillDescribedCount}/{snapshot.skills.length} 已描述，{skillTaggedCount}/{snapshot.skills.length}{' '}
                已配置分组、标签或调用策略。
              </p>
            </div>
            <div className="signal-card">
              <strong>TOOLS 可靠性信号</strong>
              <p>
                {reliability.documented}/{snapshot.tools.length} 已描述，
                {` ${reliability.typed}/${snapshot.tools.length} 已解析 Schema。`}
              </p>
            </div>
          </div>
        </article>
      </section>

      <section className="workspace-grid-three">
        <article className="workspace-surface">
          <div className="surface-heading">
            <span>最近技能</span>
          </div>
          <div className="document-list">
            {recentSkills.map(skill => (
              <button
                aria-label={`Open skill ${skill.name}`}
                className="document-card document-button"
                key={skill.id}
                onClick={() => openSkillDetail(skill.id)}
                type="button"
              >
                <strong>{skill.name}</strong>
                <p>{skill.description || skill.file_path}</p>
                {skill.modified_at && <span>{formatRelativeTime(skill.modified_at)}</span>}
              </button>
            ))}
            {snapshot.skills.length === 0 && <div className="empty-surface">No skills found.</div>}
          </div>
        </article>

        <article className="workspace-surface">
          <div className="surface-heading">
            <span>最近工具</span>
          </div>
          <div className="document-list">
            {recentTools.map(tool => (
              <button
                aria-label={`Open tool ${tool.name}`}
                className="document-card document-button"
                key={tool.name}
                onClick={() => openToolDetail(tool.name)}
                type="button"
              >
                <strong>{tool.name}</strong>
                <p>{tool.description || tool.file_path}</p>
                {tool.modified_at && <span>{formatRelativeTime(tool.modified_at)}</span>}
              </button>
            ))}
            {snapshot.tools.length === 0 && <div className="empty-surface">No tools found.</div>}
          </div>
        </article>

        <article className="workspace-surface">
          <div className="surface-heading">
            <span>最近记忆</span>
          </div>
          <div className="document-list">
            {recentFiles.map(file => (
              <button
                aria-label={`Open memory file ${file.file_path}`}
                className="document-card document-button"
                key={`${file.user_id}-${file.file_path}`}
                onClick={() => openMemoryDetail(file.file_path, file.user_id)}
                type="button"
              >
                <strong>{`${file.user_id}/${file.file_path.split('/').pop() || file.file_path}`}</strong>
                <p>{file.file_type}</p>
                {file.modified_at && <span>{formatRelativeTime(file.modified_at)}</span>}
              </button>
            ))}
            {snapshot.files.length === 0 && <div className="empty-surface">No memory files found.</div>}
          </div>
        </article>
      </section>
    </>
  )
}

function SkillsSection({ agentId }: { agentId: string }) {
  const [searchParams] = useSearchParams()
  const { user } = useAuth()
  const canEdit = user?.role === 'editor'
  const [skills, setSkills] = useState<SkillMeta[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<ViewMode>('view')
  const [feedback, setFeedback] = useState<string | null>(null)
  const [formName, setFormName] = useState('')
  const [formDescription, setFormDescription] = useState('')
  const [formContent, setFormContent] = useState('')
  const [query, setQuery] = useState('')

  const selectedSkill = useMemo(
    () => skills.find(skill => skill.id === selectedId) ?? null,
    [selectedId, skills],
  )
  const filteredSkills = useMemo(() => {
    const value = query.trim().toLowerCase()
    if (!value) return skills
    return skills.filter(skill => {
      const tags = skill.tags?.join(' ').toLowerCase() || ''
      return (
        skill.name.toLowerCase().includes(value) ||
        skill.id.toLowerCase().includes(value) ||
        (skill.description || '').toLowerCase().includes(value) ||
        (skill.file_path || '').toLowerCase().includes(value) ||
        tags.includes(value)
      )
    })
  }, [query, skills])
  const requestedSkillId = searchParams.get('skill')

  const loadSkills = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextSkills = await api.listSkills(agentId)
      setSkills(nextSkills)
      setSelectedId(prev => {
        if (requestedSkillId && nextSkills.some(skill => skill.id === requestedSkillId)) {
          return requestedSkillId
        }
        return prev ?? nextSkills[0]?.id ?? null
      })
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError))
    } finally {
      setLoading(false)
    }
  }, [agentId, requestedSkillId])

  useEffect(() => {
    void loadSkills()
  }, [loadSkills])

  useEffect(() => {
    if (!requestedSkillId) return
    const match = skills.find(skill => skill.id === requestedSkillId)
    if (!match) return
    setSelectedId(match.id)
    setMode('view')
  }, [requestedSkillId, skills])

  useEffect(() => {
    if (mode === 'edit' && selectedSkill) {
      setFormName(selectedSkill.name)
      setFormDescription(selectedSkill.description || '')
      setFormContent(selectedSkill.content || '')
    }
  }, [mode, selectedSkill])

  function resetForm() {
    setFormName('')
    setFormDescription('')
    setFormContent('')
  }

  async function handleCreate() {
    try {
      const created = await api.createSkill(agentId, {
        name: formName,
        description: formDescription,
        content: formContent,
      })
      setFeedback(`Created skill ${created.name}`)
      setMode('view')
      resetForm()
      await loadSkills()
      setSelectedId(created.id)
    } catch (nextError) {
      setFeedback(nextError instanceof Error ? nextError.message : String(nextError))
    }
  }

  async function handleUpdate() {
    if (!selectedSkill) return
    try {
      const updated = await api.updateSkill(agentId, selectedSkill.id, {
        name: formName,
        description: formDescription,
        content: formContent,
      })
      setFeedback(`Updated skill ${updated.name}`)
      setMode('view')
      await loadSkills()
      setSelectedId(updated.id)
    } catch (nextError) {
      setFeedback(nextError instanceof Error ? nextError.message : String(nextError))
    }
  }

  async function handleDelete() {
    if (!selectedSkill) return
    try {
      await api.deleteSkill(agentId, selectedSkill.id)
      setFeedback(`Deleted skill ${selectedSkill.name}`)
      setSelectedId(null)
      setMode('view')
      await loadSkills()
    } catch (nextError) {
      setFeedback(nextError instanceof Error ? nextError.message : String(nextError))
    }
  }

  if (loading) return <div className="empty-surface">Loading skills...</div>
  if (error) return <div className="empty-surface">{error}</div>

  return (
    <section className="workspace-split">
      <div className="workspace-surface split-list">
        <div className="surface-heading">
          <span>Skills</span>
          <span>{skills.length}</span>
        </div>
        <div className="panel-search-row">
          <label className="panel-search">
            <input
              aria-label="Search skills"
              onChange={event => setQuery(event.target.value)}
              placeholder="Search skills"
              value={query}
            />
          </label>
          {canEdit && (
            <button
              aria-label="Create new skill"
              className="panel-icon-button"
              onClick={() => {
                setMode('create')
                setSelectedId(null)
                resetForm()
              }}
              title="New skill"
              type="button"
            >
              <PlusIcon />
            </button>
          )}
        </div>
        <div className="document-list">
          {filteredSkills.map(skill => (
            <button
              className={`document-card document-button skill-list-card ${
                selectedId === skill.id && mode === 'view' ? 'active' : ''
              }`}
              key={skill.id}
              onClick={() => {
                setSelectedId(skill.id)
                setMode('view')
              }}
              type="button"
            >
              <div className="skill-list-card-top">
                <strong>{skill.name}</strong>
                <span className="skill-policy-chip">{skill.invocation_policy || 'manual'}</span>
              </div>
              <p>{skill.description || skill.file_path}</p>
            </button>
          ))}
          {skills.length === 0 && <div className="empty-surface">No skills found.</div>}
          {skills.length > 0 && filteredSkills.length === 0 && <div className="empty-surface">No matching skills.</div>}
        </div>
      </div>

      <div className="workspace-surface split-detail">
        {feedback && <div className="feedback-banner">{feedback}</div>}

        {(mode === 'create' || mode === 'edit') && (
          <div className="editor-sheet">
            <div className="surface-heading">
              <span>{mode === 'create' ? 'Create Skill' : 'Edit Skill'}</span>
            </div>
            <label className="form-field">
              <span>Name</span>
              <input onChange={event => setFormName(event.target.value)} value={formName} />
            </label>
            <label className="form-field">
              <span>Description</span>
              <textarea
                onChange={event => setFormDescription(event.target.value)}
                rows={3}
                value={formDescription}
              />
            </label>
            <label className="form-field">
              <span>SKILL.md Content</span>
              <textarea
                onChange={event => setFormContent(event.target.value)}
                rows={16}
                spellCheck={false}
                value={formContent}
              />
            </label>
            <div className="button-row">
              <button
                className="action-button action-button-primary"
                disabled={!formName.trim()}
                onClick={() => void (mode === 'create' ? handleCreate() : handleUpdate())}
                type="button"
              >
                {mode === 'create' ? 'Create Skill' : 'Save Skill'}
              </button>
              <button className="action-button" onClick={() => setMode('view')} type="button">
                Cancel
              </button>
            </div>
          </div>
        )}

        {mode === 'view' && selectedSkill && (
          <div className="editor-sheet">
            <div className="surface-heading">
              <span>{selectedSkill.name}</span>
              {canEdit && (
                <div className="button-row">
                  <button className="action-button" onClick={() => setMode('edit')} type="button">
                    Edit
                  </button>
                  <button className="action-button action-button-danger" onClick={() => void handleDelete()} type="button">
                    Delete
                  </button>
                </div>
              )}
            </div>

            <div className="content-card skill-metadata-card">
              <h3>Skill Metadata</h3>
              <div className="metadata-table-shell">
                <table className="metadata-table skill-metadata-table">
                  <tbody>
                    <tr>
                      <th scope="row">Skill ID</th>
                      <td>
                        <code>{selectedSkill.id}</code>
                      </td>
                    </tr>
                    <tr>
                      <th scope="row">Version</th>
                      <td>{selectedSkill.version || '—'}</td>
                    </tr>
                    <tr>
                      <th scope="row">Policy</th>
                      <td>{selectedSkill.invocation_policy || 'manual'}</td>
                    </tr>
                    <tr>
                      <th scope="row">Group</th>
                      <td>{selectedSkill.group || 'default'}</td>
                    </tr>
                    <tr>
                      <th scope="row">Tags</th>
                      <td>
                        {selectedSkill.tags && selectedSkill.tags.length > 0 ? (
                          <div className="metadata-tag-list" role="list" aria-label="Skill tags">
                            {selectedSkill.tags.map(tag => (
                              <span className="metadata-tag" key={tag} role="listitem">
                                {tag}
                              </span>
                            ))}
                          </div>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                    <tr>
                      <th scope="row">File Path</th>
                      <td>
                        <code>{selectedSkill.file_path}</code>
                      </td>
                    </tr>
                    <tr>
                      <th scope="row">Updated</th>
                      <td>
                        {selectedSkill.modified_at ? formatRelativeTime(selectedSkill.modified_at) : '—'}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div className="content-card">
              <h3>Prompt and Guidelines</h3>
              <pre className="code-block">{selectedSkill.content || 'File is empty.'}</pre>
            </div>
          </div>
        )}

        {mode === 'view' && !selectedSkill && (
          <div className="empty-surface">Select a skill or create a new one.</div>
        )}
      </div>
    </section>
  )
}

function ToolsSection({ agentId }: { agentId: string }) {
  const [searchParams] = useSearchParams()
  const { user } = useAuth()
  const canEdit = user?.role === 'editor'
  const [tools, setTools] = useState<ToolMeta[]>([])
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const [mode, setMode] = useState<ViewMode>('view')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [formName, setFormName] = useState('')
  const [formDescription, setFormDescription] = useState('')
  const [query, setQuery] = useState('')

  const selectedTool = useMemo(
    () => tools.find(tool => tool.name === selectedName) ?? null,
    [selectedName, tools],
  )
  const filteredTools = useMemo(() => {
    const value = query.trim().toLowerCase()
    if (!value) return tools
    return tools.filter(tool => {
      return (
        tool.name.toLowerCase().includes(value) ||
        tool.group.toLowerCase().includes(value) ||
        (tool.description || '').toLowerCase().includes(value) ||
        tool.file_path.toLowerCase().includes(value)
      )
    })
  }, [query, tools])
  const requestedToolName = searchParams.get('tool')

  const loadTools = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextTools = await api.listTools(agentId)
      setTools(nextTools)
      setSelectedName(prev => {
        if (requestedToolName && nextTools.some(tool => tool.name === requestedToolName)) {
          return requestedToolName
        }
        return prev ?? nextTools[0]?.name ?? null
      })
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError))
    } finally {
      setLoading(false)
    }
  }, [agentId, requestedToolName])

  useEffect(() => {
    void loadTools()
  }, [loadTools])

  useEffect(() => {
    if (!requestedToolName) return
    const match = tools.find(tool => tool.name === requestedToolName)
    if (!match) return
    setSelectedName(match.name)
    setMode('view')
  }, [requestedToolName, tools])

  async function handleScaffold() {
    try {
      const created = await api.scaffoldTool(agentId, {
        name: formName,
        description: formDescription,
      })
      setFeedback(`Generated tool scaffold ${created.name}`)
      setMode('view')
      setFormName('')
      setFormDescription('')
      await loadTools()
      setSelectedName(created.name)
    } catch (nextError) {
      setFeedback(nextError instanceof Error ? nextError.message : String(nextError))
    }
  }

  if (loading) return <div className="empty-surface">Loading tools...</div>
  if (error) return <div className="empty-surface">{error}</div>

  return (
    <section className="workspace-split">
      <div className="workspace-surface split-list">
        <div className="surface-heading">
          <span>Tools</span>
          <span>{tools.length}</span>
        </div>
        <div className="panel-search-row">
          <label className="panel-search">
            <input
              aria-label="Search tools"
              onChange={event => setQuery(event.target.value)}
              placeholder="Search tools"
              value={query}
            />
          </label>
          {canEdit && (
            <button
              aria-label="Create new tool"
              className="panel-icon-button"
              onClick={() => {
                setMode('scaffold')
                setSelectedName(null)
              }}
              title="New tool"
              type="button"
            >
              <PlusIcon />
            </button>
          )}
        </div>
        <div className="document-list">
          {filteredTools.map(tool => (
            <button
              className={`document-card document-button tool-list-card ${
                selectedName === tool.name && mode === 'view' ? 'active' : ''
              }`}
              key={tool.name}
              onClick={() => {
                setSelectedName(tool.name)
                setMode('view')
              }}
              type="button"
            >
              <div className="skill-list-card-top">
                <strong>{tool.name}</strong>
                <span className="skill-policy-chip">{tool.group || 'default'}</span>
              </div>
              <p>{tool.description || tool.file_path}</p>
            </button>
          ))}
          {tools.length === 0 && <div className="empty-surface">No tools found.</div>}
          {tools.length > 0 && filteredTools.length === 0 && <div className="empty-surface">No matching tools.</div>}
        </div>
      </div>

      <div className="workspace-surface split-detail">
        {feedback && <div className="feedback-banner">{feedback}</div>}
        {mode === 'scaffold' && (
          <div className="editor-sheet">
            <div className="surface-heading">
              <span>Generate Tool Scaffold</span>
            </div>
            <label className="form-field">
              <span>Python identifier</span>
              <input onChange={event => setFormName(event.target.value)} value={formName} />
            </label>
            <label className="form-field">
              <span>Description</span>
              <input
                onChange={event => setFormDescription(event.target.value)}
                value={formDescription}
              />
            </label>
            <div className="button-row">
              <button
                className="action-button action-button-primary"
                disabled={!formName.trim()}
                onClick={() => void handleScaffold()}
                type="button"
              >
                Generate
              </button>
              <button className="action-button" onClick={() => setMode('view')} type="button">
                Cancel
              </button>
            </div>
          </div>
        )}

        {mode === 'view' && selectedTool && (
          <div className="editor-sheet">
            <div className="surface-heading">
              <span>{selectedTool.name}</span>
            </div>
            <div className="content-card skill-metadata-card">
              <h3>Tool Metadata</h3>
              <div className="metadata-table-shell">
                <table className="metadata-table">
                  <tbody>
                    <tr>
                      <th scope="row">Tool Name</th>
                      <td>
                        <code>{selectedTool.name}</code>
                      </td>
                    </tr>
                    <tr>
                      <th scope="row">Group</th>
                      <td>{selectedTool.group || 'default'}</td>
                    </tr>
                    <tr>
                      <th scope="row">File Path</th>
                      <td>
                        <code>{selectedTool.file_path}</code>
                      </td>
                    </tr>
                    <tr>
                      <th scope="row">Updated</th>
                      <td>{selectedTool.modified_at ? formatRelativeTime(selectedTool.modified_at) : '—'}</td>
                    </tr>
                    <tr>
                      <th scope="row">Parameters</th>
                      <td>{Object.keys(selectedTool.parameters || {}).length}</td>
                    </tr>
                    <tr>
                      <th scope="row">Description</th>
                      <td>{selectedTool.description || '—'}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <StructuredDataCard
              emptyText="// No parameters defined"
              title="Parameter Schema"
              value={
                Object.keys(selectedTool.parameters || {}).length > 0
                  ? JSON.stringify(selectedTool.parameters, null, 2)
                  : ''
              }
            />
          </div>
        )}

        {mode === 'view' && !selectedTool && <div className="empty-surface">Select a tool or scaffold a new one.</div>}
      </div>
    </section>
  )
}

function SessionsSection({ agentId }: { agentId: string }) {
  const { user } = useAuth()
  const canEdit = user?.role === 'editor'
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [selected, setSelected] = useState<SessionItem | null>(null)
  const [collapsedUserGroups, setCollapsedUserGroups] = useState<Set<string>>(() => new Set())
  const [query, setQuery] = useState('')
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [rawText, setRawText] = useState('')
  const [rawDraft, setRawDraft] = useState('')
  const [tab, setTab] = useState<'conversation' | 'execution' | 'raw'>('conversation')
  const [editingRaw, setEditingRaw] = useState(false)
  const [sessionPanelsExpanded, setSessionPanelsExpanded] = useState(false)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [feedbackTone, setFeedbackTone] = useState<'status' | 'alert'>('status')

  const groupedSessions = useMemo(() => {
    const byUser = new Map<string, SessionItem[]>()
    for (const session of sessions) {
      const value = query.trim().toLowerCase()
      const sessionLabel = `${session.user_id} ${session.session_id} ${session.first_message ?? ''}`.toLowerCase()
      if (value && !sessionLabel.includes(value)) continue
      const key = session.user_id || '(anonymous)'
      const list = byUser.get(key) ?? []
      list.push(session)
      byUser.set(key, list)
    }
    return [...byUser.entries()]
  }, [query, sessions])

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      setFeedback(null)
      try {
        const nextSessions = await api.listSessions(agentId)
        if (!cancelled) {
          setSessions(nextSessions)
          setSelected(nextSessions[0] ?? null)
        }
      } catch (nextError) {
        if (!cancelled) setError(nextError instanceof Error ? nextError.message : String(nextError))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [agentId])

  useEffect(() => {
    if (!selected) return
    const currentSession = selected

    let cancelled = false

    async function loadTabData() {
      setDetailLoading(true)
      try {
        if (tab === 'conversation' || tab === 'execution') {
          const nextDetail = await api.getSessionDetail(
            agentId,
            currentSession.session_id,
            currentSession.user_id,
          )
          if (!cancelled) setDetail(nextDetail)
        } else {
          const nextRaw = await api.getSessionRaw(
            agentId,
            currentSession.session_id,
            currentSession.user_id,
          )
          if (!cancelled) {
            setRawText(nextRaw)
            setRawDraft(nextRaw)
          }
        }
      } catch (nextError) {
        if (!cancelled) {
          setFeedback(nextError instanceof Error ? nextError.message : String(nextError))
          setFeedbackTone('alert')
        }
      } finally {
        if (!cancelled) setDetailLoading(false)
      }
    }

    void loadTabData()
    return () => {
      cancelled = true
    }
  }, [agentId, selected, tab])

  useEffect(() => {
    setSessionPanelsExpanded(false)
  }, [selected?.session_id])

  useEffect(() => {
    if (sessions.length === 0) {
      setCollapsedUserGroups(new Set())
      return
    }
    setCollapsedUserGroups(new Set(sessions.map(session => session.user_id || '(anonymous)')))
  }, [sessions])

  const toggleUserGroup = useCallback((userId: string) => {
    setCollapsedUserGroups(current => {
      const next = new Set(current)
      if (next.has(userId)) {
        next.delete(userId)
      } else {
        next.add(userId)
      }
      return next
    })
  }, [])

  async function saveRaw() {
    if (!selected) return
    try {
      await api.putSessionRaw(agentId, selected.session_id, selected.user_id, rawDraft)
      setRawText(rawDraft)
      setEditingRaw(false)
      setFeedback('Session raw content saved.')
      setFeedbackTone('status')
    } catch (nextError) {
      setFeedback(nextError instanceof Error ? nextError.message : String(nextError))
      setFeedbackTone('alert')
    }
  }

  if (loading) return <div className="empty-surface">Loading sessions...</div>
  if (error) return <div className="empty-surface">{error}</div>

  const filteredSessionCount = groupedSessions.reduce((total, [, items]) => total + items.length, 0)
  const sessionDomId = selected ? toDomId(selected.session_id) : 'session'
  const conversationTabId = `${sessionDomId}-conversation-tab`
  const executionTabId = `${sessionDomId}-execution-tab`
  const rawTabId = `${sessionDomId}-raw-tab`
  const conversationPanelId = `${sessionDomId}-conversation-panel`
  const executionPanelId = `${sessionDomId}-execution-panel`
  const rawPanelId = `${sessionDomId}-raw-panel`
  const canToggleSessionPanels = tab === 'conversation' || (tab === 'raw' && !editingRaw)
  const sessionPanelToggleLabel = sessionPanelsExpanded ? 'Collapse all' : 'Expand all'

  return (
    <section className="workspace-split workspace-sessions">
      <div className="workspace-surface split-list session-nav-panel">
        <div className="surface-heading">
          <span>Sessions</span>
          <span>{filteredSessionCount}</span>
        </div>
        <label className="session-search">
          <input
            aria-label="Search sessions"
            onChange={event => setQuery(event.target.value)}
            placeholder="Search sessions"
            value={query}
          />
        </label>
        <div aria-label="Sessions" className="session-nav-list" role="list">
          {groupedSessions.map(([userId, items]) => {
            const isCollapsed = collapsedUserGroups.has(userId)
            const sessionGroupId = `${toDomId(userId)}-sessions-group`
            return (
            <div className="session-cluster" key={userId}>
              <div className="session-cluster-head">
                <button
                  aria-controls={sessionGroupId}
                  aria-expanded={!isCollapsed}
                  className={`session-cluster-toggle ${isCollapsed ? 'collapsed' : ''}`}
                  onClick={() => toggleUserGroup(userId)}
                  type="button"
                >
                  <span className="session-group-title">
                    <ChevronRightIcon className="session-group-chevron" />
                    <span>{userId}</span>
                  </span>
                  <span>{items.length}</span>
                </button>
              </div>
              <div className={`session-cluster-items ${isCollapsed ? 'collapsed' : ''}`} id={sessionGroupId}>
                {items.map(session => (
                <button
                  aria-label={`Session ${session.first_message || session.session_id}`}
                  className={`session-nav-card ${selected?.session_id === session.session_id ? 'active' : ''}`}
                  key={session.session_id}
                  onFocus={() => {
                    setSelected(session)
                    setEditingRaw(false)
                  }}
                  onClick={() => {
                    setSelected(session)
                    setEditingRaw(false)
                  }}
                  type="button"
                >
                  <div className="session-nav-card-top">
                    <strong>{session.first_message || session.session_id.slice(0, 14)}</strong>
                    <span>{formatRelativeTime(session.updated_at || session.created_at)}</span>
                  </div>
                  <p>{session.session_id}</p>
                  <div className="session-nav-card-meta">
                    <span>{session.message_count} messages</span>
                    <span>{session.user_id}</span>
                  </div>
                </button>
                ))}
              </div>
            </div>
            )
          })}
          {filteredSessionCount === 0 && <div className="empty-surface">No sessions found.</div>}
        </div>
      </div>

      <div className="workspace-surface split-detail session-detail-panel">
        <div className="surface-heading">
          <span>Session Detail</span>
        </div>
        <div aria-atomic="true" aria-live="polite" className="sr-only">
          {detailLoading
            ? 'Loading session detail'
            : selected
              ? `Viewing session ${selected.first_message || selected.session_id}, ${tab} tab`
              : 'No session selected'}
        </div>
        {feedback && (
          <div
            aria-live={feedbackTone === 'alert' ? 'assertive' : 'polite'}
            className="feedback-banner"
            role={feedbackTone}
          >
            {feedback}
          </div>
        )}

        {!selected && <div className="empty-surface">Select a session to inspect evidence.</div>}

        {selected && (
          <div className="editor-sheet">
            <div className="workspace-grid-three">
              <div className="metric-surface session-summary-card">
                <span>User ID</span>
                <strong>{selected.user_id}</strong>
              </div>
              <div className="metric-surface session-summary-card">
                <span>Messages</span>
                <strong>{selected.message_count}</strong>
              </div>
              <div className="metric-surface session-summary-card">
                <span>Updated</span>
                <strong>{formatRelativeTime(selected.updated_at || selected.created_at)}</strong>
              </div>
            </div>

            <div className="session-detail-hero">
              <div className="session-detail-hero-top">
                <div className="session-detail-hero-copy">
                  <h2>{selected.first_message || selected.session_id}</h2>
                  <p>{selected.session_id}</p>
                </div>
                <div className="session-detail-hero-actions">
                  <button
                    aria-label={sessionPanelToggleLabel}
                    className="icon-action-button session-detail-bulk-toggle"
                    disabled={!canToggleSessionPanels}
                    onClick={() => setSessionPanelsExpanded(current => !current)}
                    type="button"
                  >
                    {sessionPanelsExpanded ? <CollapseIcon /> : <ExpandIcon />}
                  </button>
                </div>
              </div>
              <div aria-label="Session detail views" className="session-mode-switch" role="tablist">
                <button
                  aria-controls={conversationPanelId}
                  aria-selected={tab === 'conversation'}
                  className={`action-button session-mode-switch-button ${tab === 'conversation' ? 'action-button-primary' : ''}`}
                  id={conversationTabId}
                  onFocus={() => setTab('conversation')}
                  onClick={() => setTab('conversation')}
                  role="tab"
                  type="button"
                >
                  Conversation
                </button>
                <button
                  aria-controls={executionPanelId}
                  aria-selected={tab === 'execution'}
                  className={`action-button session-mode-switch-button ${tab === 'execution' ? 'action-button-primary' : ''}`}
                  id={executionTabId}
                  onFocus={() => setTab('execution')}
                  onClick={() => setTab('execution')}
                  role="tab"
                  type="button"
                >
                  Execution
                </button>
                <button
                  aria-controls={rawPanelId}
                  aria-selected={tab === 'raw'}
                  className={`action-button session-mode-switch-button ${tab === 'raw' ? 'action-button-primary' : ''}`}
                  id={rawTabId}
                  onFocus={() => setTab('raw')}
                  onClick={() => setTab('raw')}
                  role="tab"
                  type="button"
                >
                  Raw JSONL
                </button>
              </div>
            </div>

            {detailLoading && <div className="empty-surface">Loading session detail...</div>}

            {!detailLoading && tab === 'conversation' && detail && (
              <div
                aria-labelledby={conversationTabId}
                className="editor-sheet"
                id={conversationPanelId}
                role="tabpanel"
              >
                <StructuredDataCard
                  emptyText="// No session state recorded"
                  expandedOverride={sessionPanelsExpanded}
                  title="State"
                  value={
                    Object.keys(detail.state || {}).length > 0
                      ? JSON.stringify(detail.state, null, 2)
                      : ''
                  }
                />
                <div className="message-stack">
                  {detail.messages.map((message, index) => (
                    <SessionMessageCard
                      allPanelsExpanded={sessionPanelsExpanded}
                      key={`${message.role}-${index}`}
                      message={message}
                      messageIndex={index}
                    />
                  ))}
                </div>
              </div>
            )}

            {!detailLoading && tab === 'execution' && detail && (
              <ExecutionSection
                detail={detail}
                panelId={executionPanelId}
                sessionDomId={sessionDomId}
                tabId={executionTabId}
              />
            )}

            {!detailLoading && tab === 'raw' && (
              <div aria-labelledby={rawTabId} className="content-card" id={rawPanelId} role="tabpanel">
                {editingRaw ? (
                  <>
                    <div className="surface-heading">
                      <h3>Raw JSONL</h3>
                      {canEdit && (
                        <div className="button-row">
                          <button className="action-button action-button-primary" onClick={() => void saveRaw()} type="button">
                            Save
                          </button>
                          <button className="action-button" onClick={() => setEditingRaw(false)} type="button">
                            Cancel
                          </button>
                        </div>
                      )}
                    </div>
                    <textarea
                      className="code-textarea"
                      onChange={event => setRawDraft(event.target.value)}
                      rows={18}
                      spellCheck={false}
                      value={rawDraft}
                    />
                  </>
                ) : (
                  <StructuredDataCard
                    emptyText="// Empty raw content"
                    expandedOverride={sessionPanelsExpanded}
                    extraActions={
                      canEdit ? (
                        <button className="action-button" onClick={() => setEditingRaw(true)} type="button">
                          Edit
                        </button>
                      ) : undefined
                    }
                    title="Raw JSONL"
                    value={rawText}
                  />
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

function ExecutionSection({
  detail,
  panelId,
  sessionDomId,
  tabId,
}: {
  detail: SessionDetail
  panelId: string
  sessionDomId: string
  tabId: string
}) {
  const rounds = useMemo(() => buildExecutionRounds(detail), [detail])
  const summary = useMemo(() => summarizeExecutionRounds(rounds), [rounds])
  const [selectedRound, setSelectedRound] = useState<number | null>(rounds[0]?.round ?? null)
  const [scrollRoundStart, setScrollRoundStart] = useState(0)
  const [focusedLane, setFocusedLane] = useState<TraceLane | null>(null)
  const [roundsDragging, setRoundsDragging] = useState(false)
  const roundsPanelRef = useRef<HTMLElement | null>(null)
  const pageScrollStyleRef = useRef<{
    htmlOverflow: string
    bodyOverflow: string
    workspaceOverflow: string
    workspacePaddingRight: string
  } | null>(null)
  const roundScrollerRef = useRef<HTMLDivElement | null>(null)
  const roundCardRefs = useRef<Record<number, HTMLButtonElement | null>>({})
  const traceLegendRefs = useRef<Record<TraceLane, HTMLButtonElement | null>>({
    input: null,
    reasoning: null,
    tools: null,
    output: null,
    metadata: null,
  })
  const lastWheelShiftAtRef = useRef(0)
  const dragPointerIdRef = useRef<number | null>(null)
  const dragStartXRef = useRef(0)
  const dragStartScrollLeftRef = useRef(0)
  const suppressCardClickRef = useRef(false)

  useEffect(() => {
    setSelectedRound(current =>
      rounds.some(round => round.round === current) ? current : (rounds[0]?.round ?? null),
    )
  }, [rounds])

  const activeRound =
    rounds[scrollRoundStart] ??
    rounds.find(round => round.round === selectedRound) ??
    rounds[0] ??
    null
  const canShiftPrev = rounds.length > 1
  const canShiftNext = rounds.length > 1

  const updateRoundCardMotion = useCallback(() => {
    const scroller = roundScrollerRef.current
    if (!scroller || rounds.length === 0) return

    const viewportCenter = scroller.scrollLeft + scroller.clientWidth / 2

    for (const round of rounds) {
      const card = roundCardRefs.current[round.round]
      if (!card) continue

      const cardCenter = card.offsetLeft + card.offsetWidth / 2
      const normalizedProgress = Math.max(
        -1.25,
        Math.min(1.25, (cardCenter - viewportCenter) / Math.max(card.offsetWidth, 1)),
      )
      const absProgress = Math.abs(normalizedProgress)

      card.style.setProperty('--round-progress', normalizedProgress.toFixed(4))
      card.style.setProperty('--round-abs-progress', absProgress.toFixed(4))
    }
  }, [rounds])

  const syncRoundSelectionFromScroll = useCallback(() => {
    const scroller = roundScrollerRef.current
    if (!scroller || rounds.length === 0) return

    let closestIndex = 0
    let closestOffset = Number.POSITIVE_INFINITY
    const viewportCenter = scroller.scrollLeft + scroller.clientWidth / 2

    for (let index = 0; index < rounds.length; index += 1) {
      const card = roundCardRefs.current[rounds[index].round]
      if (!card) continue
      const cardCenter = card.offsetLeft + card.offsetWidth / 2
      const offset = Math.abs(cardCenter - viewportCenter)
      if (offset < closestOffset) {
        closestOffset = offset
        closestIndex = index
      }
    }

    updateRoundCardMotion()
    setScrollRoundStart(current => (current === closestIndex ? current : closestIndex))
    setSelectedRound(current => (current === rounds[closestIndex]?.round ? current : (rounds[closestIndex]?.round ?? null)))
  }, [rounds, updateRoundCardMotion])

  const scrollToRound = useCallback(
    (roundNumber: number, behavior: ScrollBehavior = 'smooth') => {
      const scroller = roundScrollerRef.current
      const card = roundCardRefs.current[roundNumber]
      if (!scroller || !card) return

      scroller.scrollTo({
        left: Math.max(0, card.offsetLeft - (scroller.clientWidth - card.offsetWidth) / 2),
        behavior,
      })
      const nextIndex = rounds.findIndex(round => round.round === roundNumber)
      if (nextIndex !== -1) {
        setScrollRoundStart(nextIndex)
        setSelectedRound(roundNumber)
      }
    },
    [rounds],
  )

  useEffect(() => {
    if (rounds.length === 0) {
      setScrollRoundStart(0)
      return
    }

    const selected =
      selectedRound && rounds.some(round => round.round === selectedRound)
        ? selectedRound
        : rounds[0].round

    setSelectedRound(selected)
    setScrollRoundStart(Math.max(0, rounds.findIndex(round => round.round === selected)))

    requestAnimationFrame(() => {
      scrollToRound(selected, 'auto')
      updateRoundCardMotion()
    })
  }, [rounds, scrollToRound, updateRoundCardMotion])

  const lockPageScroll = useCallback(() => {
    if (pageScrollStyleRef.current) return
    const workspace = roundsPanelRef.current?.closest('.studio-workspace') as HTMLElement | null
    const workspaceScrollbarWidth = workspace ? workspace.offsetWidth - workspace.clientWidth : 0
    pageScrollStyleRef.current = {
      htmlOverflow: document.documentElement.style.overflow,
      bodyOverflow: document.body.style.overflow,
      workspaceOverflow: workspace?.style.overflow ?? '',
      workspacePaddingRight: workspace?.style.paddingRight ?? '',
    }
    document.documentElement.style.overflow = 'hidden'
    document.body.style.overflow = 'hidden'
    if (workspace) {
      workspace.style.overflow = 'hidden'
      workspace.style.paddingRight = `calc(4px + ${workspaceScrollbarWidth}px)`
    }
  }, [])

  const unlockPageScroll = useCallback(() => {
    if (!pageScrollStyleRef.current) return
    const workspace = roundsPanelRef.current?.closest('.studio-workspace') as HTMLElement | null
    document.documentElement.style.overflow = pageScrollStyleRef.current.htmlOverflow
    document.body.style.overflow = pageScrollStyleRef.current.bodyOverflow
    if (workspace) {
      workspace.style.overflow = pageScrollStyleRef.current.workspaceOverflow
      workspace.style.paddingRight = pageScrollStyleRef.current.workspacePaddingRight
    }
    pageScrollStyleRef.current = null
  }, [])

  useEffect(() => {
    return () => {
      unlockPageScroll()
    }
  }, [unlockPageScroll])

  function shiftRoundWindow(direction: -1 | 1) {
    if (rounds.length === 0) return
    const nextIndex = (scrollRoundStart + direction + rounds.length) % rounds.length
    const nextRound = rounds[nextIndex]?.round
    if (nextRound) scrollToRound(nextRound)
  }

  function handleRoundScrollerPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    const scroller = roundScrollerRef.current
    if (!scroller) return
    dragPointerIdRef.current = event.pointerId
    dragStartXRef.current = event.clientX
    dragStartScrollLeftRef.current = scroller.scrollLeft
    scroller.setPointerCapture(event.pointerId)
    setRoundsDragging(true)
  }

  function handleRoundScrollerPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const scroller = roundScrollerRef.current
    if (!scroller || dragPointerIdRef.current !== event.pointerId) return

    const deltaX = event.clientX - dragStartXRef.current
    if (Math.abs(deltaX) > 6) suppressCardClickRef.current = true
    scroller.scrollLeft = dragStartScrollLeftRef.current - deltaX
  }

  function handleRoundScrollerPointerEnd(event: ReactPointerEvent<HTMLDivElement>) {
    const scroller = roundScrollerRef.current
    if (!scroller || dragPointerIdRef.current !== event.pointerId) return

    if (scroller.hasPointerCapture(event.pointerId)) {
      scroller.releasePointerCapture(event.pointerId)
    }
    dragPointerIdRef.current = null
    setRoundsDragging(false)
    syncRoundSelectionFromScroll()

    if (suppressCardClickRef.current) {
      window.setTimeout(() => {
        suppressCardClickRef.current = false
      }, 0)
    }
  }

  function handleRoundCardSelect(roundNumber: number) {
    if (suppressCardClickRef.current) return
    scrollToRound(roundNumber)
  }

  function handleRoundsPanelWheel(event: ReactWheelEvent<HTMLElement>) {
    event.preventDefault()
    event.stopPropagation()
    if (rounds.length <= 1) return

    const dominantDelta =
      Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX
    if (Math.abs(dominantDelta) < 8) return

    const now = Date.now()
    if (now - lastWheelShiftAtRef.current < 220) return
    lastWheelShiftAtRef.current = now

    shiftRoundWindow(dominantDelta > 0 ? 1 : -1)
  }

  function handleRoundsPanelPointerEnter() {
    lockPageScroll()
  }

  function handleRoundsPanelPointerLeave() {
    unlockPageScroll()
  }

  function handleTraceLegendSelect(lane: TraceLane) {
    setFocusedLane(current => (current === lane ? null : lane))
  }

  function focusTraceLegendTab(lane: TraceLane) {
    traceLegendRefs.current[lane]?.focus()
  }

  function handleTraceLegendKeyDown(
    event: ReactKeyboardEvent<HTMLButtonElement>,
    currentLane: TraceLane,
  ) {
    const currentIndex = TRACE_LANES.indexOf(currentLane)
    if (currentIndex === -1) return

    let nextLane: TraceLane | null = null

    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      nextLane = TRACE_LANES[(currentIndex + 1) % TRACE_LANES.length]
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      nextLane = TRACE_LANES[(currentIndex - 1 + TRACE_LANES.length) % TRACE_LANES.length]
    } else if (event.key === 'Home') {
      nextLane = TRACE_LANES[0]
    } else if (event.key === 'End') {
      nextLane = TRACE_LANES[TRACE_LANES.length - 1]
    } else if (event.key === 'Tab') {
      nextLane = TRACE_LANES[
        (currentIndex + (event.shiftKey ? -1 : 1) + TRACE_LANES.length) % TRACE_LANES.length
      ]
    }

    if (!nextLane) return
    event.preventDefault()
    setFocusedLane(nextLane)
    focusTraceLegendTab(nextLane)
  }

  return (
    <div aria-labelledby={tabId} className="editor-sheet" id={panelId} role="tabpanel">
      <div className="workspace-grid-four">
        <div className="metric-surface execution-summary-card execution-metric-surface">
          <span>Conversation Rounds</span>
          <strong>{summary.roundCount}</strong>
        </div>
        <div className="metric-surface execution-summary-card execution-metric-surface">
          <span>Tool Calls</span>
          <strong>{summary.toolCallCount}</strong>
        </div>
        <div className="metric-surface execution-summary-card execution-metric-surface">
          <span>Tool Errors</span>
          <strong>{summary.toolErrorCount}</strong>
        </div>
        <div className="metric-surface execution-summary-card execution-metric-surface">
          <span>Reasoning Steps</span>
          <strong>{summary.reasoningCount}</strong>
        </div>
      </div>

      <div className="execution-stack">
        <section
          className="content-card execution-rounds-panel"
          onWheelCapture={handleRoundsPanelWheel}
          ref={roundsPanelRef}
          onPointerEnter={handleRoundsPanelPointerEnter}
          onPointerLeave={handleRoundsPanelPointerLeave}
        >
          <div className="surface-heading execution-rounds-heading">
            <span>Rounds</span>
            <span>{`${Math.min(scrollRoundStart + 1, rounds.length || 1)} / ${rounds.length}`}</span>
          </div>
          <div className="execution-rounds-carousel">
            <button
              aria-label="Show previous rounds"
              className="icon-action-button execution-carousel-button execution-carousel-button-prev"
              disabled={!canShiftPrev}
              onClick={() => shiftRoundWindow(-1)}
              type="button"
            >
              <ChevronRightIcon />
            </button>
            <div
              aria-label="Conversation rounds"
              className={`execution-round-list ${roundsDragging ? 'is-dragging' : ''}`}
              onPointerCancel={handleRoundScrollerPointerEnd}
              onPointerDown={handleRoundScrollerPointerDown}
              onPointerMove={handleRoundScrollerPointerMove}
              onPointerUp={handleRoundScrollerPointerEnd}
              onScroll={syncRoundSelectionFromScroll}
              ref={roundScrollerRef}
              role="listbox"
            >
              {rounds.map(round => (
                <button
                  aria-label={`Round ${round.round}`}
                  aria-selected={activeRound?.round === round.round}
                  className={`session-nav-card execution-round-card ${activeRound?.round === round.round ? 'active' : ''}`}
                  key={round.round}
                  onClick={() => handleRoundCardSelect(round.round)}
                  onFocus={() => scrollToRound(round.round)}
                  ref={element => {
                    roundCardRefs.current[round.round] = element
                  }}
                  role="option"
                  type="button"
                >
                  <div className="session-nav-card-top">
                    <strong>{`Round ${round.round}`}</strong>
                    <span>{round.toolCallCount} calls</span>
                  </div>
                  <p>{round.userPrompt ?? 'No user prompt recorded for this round.'}</p>
                  <div className="session-nav-card-meta execution-round-card-meta">
                    <span>{round.reasoningCount} reasoning</span>
                    <span>{round.toolErrorCount > 0 ? `${round.toolErrorCount} errors` : 'No tool errors'}</span>
                  </div>
                </button>
              ))}
              {rounds.length === 0 && <div className="empty-surface">No execution rounds were inferred from this session.</div>}
            </div>
            <button
              aria-label="Show next rounds"
              className="icon-action-button execution-carousel-button"
              disabled={!canShiftNext}
              onClick={() => shiftRoundWindow(1)}
              type="button"
            >
              <ChevronRightIcon />
            </button>
          </div>
          {rounds.length > 1 && (
            <div aria-label="Rounds pagination" className="execution-round-dots" role="tablist">
              {rounds.map((round, index) => (
                <button
                  aria-label={`Go to round ${round.round}`}
                  aria-selected={scrollRoundStart === index}
                  className={`execution-round-dot ${scrollRoundStart === index ? 'active' : ''}`}
                  key={`round-dot-${round.round}`}
                  onClick={() => scrollToRound(round.round)}
                  role="tab"
                  type="button"
                />
              ))}
            </div>
          )}
        </section>

        {activeRound ? (
          <section
            aria-labelledby={`${sessionDomId}-execution-round-${activeRound.round}`}
            className="trace-turn execution-round-detail"
          >
            <div className="trace-turn-header">
              <h3
                className="trace-turn-badge"
                id={`${sessionDomId}-execution-round-${activeRound.round}`}
              >
                {`Round ${activeRound.round}`}
              </h3>
              <span className="trace-turn-count">{`${activeRound.stages.length} event(s)`}</span>
            </div>
            <p className="execution-round-output">
              {activeRound.assistantOutput ?? 'No assistant output recorded for this round.'}
            </p>
            <div aria-label="Trace lane filters" className="trace-legend" role="toolbar">
              {TRACE_LANES.map(lane => {
                const isActive = focusedLane === lane
                const stageCount = activeRound.stages.filter(stage => stage.lane === lane).length
                return (
                  <button
                    aria-label={
                      isActive
                        ? `Clear ${executionLaneLabel(lane)} filter`
                        : `Filter to ${executionLaneLabel(lane)} lane`
                    }
                    aria-pressed={isActive}
                    className={`trace-legend-button ${isActive ? 'active' : ''}`}
                    key={`trace-legend-${lane}`}
                    onClick={() => handleTraceLegendSelect(lane)}
                    onKeyDown={event => handleTraceLegendKeyDown(event, lane)}
                    ref={element => {
                      traceLegendRefs.current[lane] = element
                    }}
                    tabIndex={focusedLane === null ? (lane === TRACE_LANES[0] ? 0 : -1) : (isActive ? 0 : -1)}
                    type="button"
                  >
                    <span>{executionLaneLabel(lane)}</span>
                    <strong>{stageCount}</strong>
                  </button>
                )
              })}
            </div>
            <div className={`trace-lane-grid ${focusedLane ? 'trace-lane-grid-focused' : ''}`}>
              {TRACE_LANES.map(lane => {
                const stages = activeRound.stages.filter(stage => stage.lane === lane)
                const isHidden = focusedLane !== null && focusedLane !== lane
                return (
                  <section
                    aria-hidden={isHidden}
                    className={`trace-lane trace-lane-${lane} ${focusedLane === lane ? 'trace-lane-active' : ''} ${isHidden ? 'trace-lane-hidden' : ''}`}
                    key={`${activeRound.round}-${lane}`}
                  >
                    <h4
                      className="trace-lane-title"
                      id={`${sessionDomId}-execution-round-${activeRound.round}-${lane}`}
                    >
                      {executionLaneLabel(lane)}
                    </h4>
                    {stages.length > 0 ? (
                      stages.map((stage, index) => (
                        <div
                          className={`trace-node trace-${stage.kind} ${stage.accent ? `trace-accent-${stage.accent}` : ''}`}
                          key={`${activeRound.round}-${lane}-${index}`}
                        >
                          <strong>{stage.label}</strong>
                          <p>{stage.preview}</p>
                        </div>
                      ))
                    ) : (
                      <div className="trace-node trace-node-empty">
                        <strong>No event</strong>
                        <p>No recorded data for this lane in the selected round.</p>
                      </div>
                    )}
                  </section>
                )
              })}
            </div>
          </section>
        ) : (
          <div className="empty-surface">No execution detail is available for this session.</div>
        )}
      </div>

      <div className="content-card">
        <h3>Inference Notes</h3>
        <p>
          This execution view is inferred from stored session detail, not from a dedicated span-tracing backend.
          It is useful for understanding prompt, reasoning, tool usage, output, and metadata flow per round.
        </p>
      </div>
    </div>
  )
}

function SessionMessageCard({
  message,
  messageIndex,
  allPanelsExpanded,
}: {
  message: MessageItem
  messageIndex: number
  allPanelsExpanded: boolean
}) {
  const messageId = `session-message-${messageIndex}-${message.role}`
  return (
    <article
      aria-labelledby={`${messageId}-title`}
      className={`session-message session-message-${message.role}`}
    >
      <h3 className="session-message-role" id={`${messageId}-title`}>
        {message.role}
      </h3>
      {message.content && <div className="session-message-content">{message.content}</div>}
      {message.thinking && (
        <section aria-labelledby={`${messageId}-thinking`} className="session-message-aside">
          <h4 id={`${messageId}-thinking`}>thinking</h4>
          <pre className="code-block compact">{message.thinking}</pre>
        </section>
      )}
      {message.tool_calls && message.tool_calls.length > 0 && (
        <section aria-labelledby={`${messageId}-tool-calls`} className="session-message-aside">
          <StructuredDataCard
            compact
            emptyText="// No tool calls"
            expandedOverride={allPanelsExpanded}
            headingId={`${messageId}-tool-calls`}
            headingLevel="h4"
            title="tool calls"
            value={JSON.stringify(message.tool_calls, null, 2)}
          />
        </section>
      )}
      {message.tool_results && message.tool_results.length > 0 && (
        <section aria-labelledby={`${messageId}-tool-results`} className="session-message-aside">
          <StructuredDataCard
            compact
            emptyText="// No tool results"
            expandedOverride={allPanelsExpanded}
            headingId={`${messageId}-tool-results`}
            headingLevel="h4"
            title="tool results"
            value={JSON.stringify(message.tool_results, null, 2)}
          />
        </section>
      )}
      {message.metadata && Object.keys(message.metadata).length > 0 && (
        <section aria-labelledby={`${messageId}-metadata`} className="session-message-aside">
          <StructuredDataCard
            compact
            emptyText="// No metadata"
            expandedOverride={allPanelsExpanded}
            headingId={`${messageId}-metadata`}
            headingLevel="h4"
            title="metadata"
            value={JSON.stringify(message.metadata, null, 2)}
          />
        </section>
      )}
    </article>
  )
}

function MemorySection({ agentId }: { agentId: string }) {
  const [searchParams] = useSearchParams()
  const { user } = useAuth()
  const canEdit = user?.role === 'editor'
  const [files, setFiles] = useState<MemoryFileItem[]>([])
  const [collapsedUserGroups, setCollapsedUserGroups] = useState<Set<string>>(() => new Set())
  const [selected, setSelected] = useState<MemoryFileItem | null>(null)
  const [content, setContent] = useState('')
  const [draft, setDraft] = useState('')
  const [editing, setEditing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [contentLoading, setContentLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const filteredFiles = useMemo(() => {
    const value = query.trim().toLowerCase()
    if (!value) return files
    return files.filter(file => {
      const fileName = file.file_path.split('/').pop()?.toLowerCase() || ''
      return (
        file.user_id.toLowerCase().includes(value) ||
        file.file_path.toLowerCase().includes(value) ||
        fileName.includes(value) ||
        file.file_type.toLowerCase().includes(value)
      )
    })
  }, [files, query])

  const groupedFiles = useMemo(() => {
    const next = new Map<string, MemoryFileItem[]>()
    for (const file of filteredFiles) {
      const key = file.user_id || '(global)'
      const list = next.get(key) ?? []
      list.push(file)
      next.set(key, list)
    }
    return [...next.entries()]
  }, [filteredFiles])
  const requestedMemoryPath = searchParams.get('memory')
  const requestedMemoryUser = searchParams.get('user') ?? ''

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const nextFiles = await api.listMemoryFiles(agentId)
        if (!cancelled) {
          setFiles(nextFiles)
          setSelected(() => {
            if (requestedMemoryPath) {
              const match = nextFiles.find(
                file => file.file_path === requestedMemoryPath && file.user_id === requestedMemoryUser,
              )
              if (match) return match
            }
            return nextFiles[0] ?? null
          })
        }
      } catch (nextError) {
        if (!cancelled) setError(nextError instanceof Error ? nextError.message : String(nextError))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [agentId, requestedMemoryPath, requestedMemoryUser])

  useEffect(() => {
    if (!requestedMemoryPath) return
    const match = files.find(
      file => file.file_path === requestedMemoryPath && file.user_id === requestedMemoryUser,
    )
    if (!match) return
    setSelected(match)
  }, [files, requestedMemoryPath, requestedMemoryUser])

  useEffect(() => {
    if (files.length === 0) {
      setCollapsedUserGroups(new Set())
      return
    }
    setCollapsedUserGroups(new Set(files.map(file => file.user_id || '(global)')))
  }, [files])

  const toggleUserGroup = useCallback((userId: string) => {
    setCollapsedUserGroups(current => {
      const next = new Set(current)
      if (next.has(userId)) {
        next.delete(userId)
      } else {
        next.add(userId)
      }
      return next
    })
  }, [])

  useEffect(() => {
    if (!selected) return
    const currentFile = selected

    let cancelled = false

    async function loadContent() {
      setContentLoading(true)
      try {
        const nextContent = await api.getMemoryContent(
          agentId,
          currentFile.file_path,
          currentFile.user_id,
        )
        if (!cancelled) {
          setContent(nextContent)
          setDraft(nextContent)
          setEditing(false)
        }
      } catch (nextError) {
        if (!cancelled) setFeedback(nextError instanceof Error ? nextError.message : String(nextError))
      } finally {
        if (!cancelled) setContentLoading(false)
      }
    }

    void loadContent()
    return () => {
      cancelled = true
    }
  }, [agentId, selected])

  async function saveMemory() {
    if (!selected) return
    try {
      await api.putMemoryContent(agentId, selected.file_path, selected.user_id, draft)
      setContent(draft)
      setEditing(false)
      setFeedback('Memory content saved.')
    } catch (nextError) {
      setFeedback(nextError instanceof Error ? nextError.message : String(nextError))
    }
  }

  if (loading) return <div className="empty-surface">Loading memory files...</div>
  if (error) return <div className="empty-surface">{error}</div>

  return (
    <section className="workspace-split">
      <div className="workspace-surface split-list">
        <div className="surface-heading">
          <span>Memory Files</span>
          <span>{files.length}</span>
        </div>
        <label className="panel-search">
          <input
            aria-label="Search memory files"
            onChange={event => setQuery(event.target.value)}
            placeholder="Search memory"
            value={query}
          />
        </label>
        <div className="document-list">
          {groupedFiles.map(([group, items]) => (
            <div className="session-cluster" key={group}>
              <div className="session-cluster-head">
                <button
                  aria-controls={`${toDomId(group)}-memory-group`}
                  aria-expanded={!collapsedUserGroups.has(group)}
                  className={`session-cluster-toggle ${collapsedUserGroups.has(group) ? 'collapsed' : ''}`}
                  onClick={() => toggleUserGroup(group)}
                  type="button"
                >
                  <span className="session-group-title">
                    <ChevronRightIcon className="session-group-chevron" />
                    <span>{group}</span>
                  </span>
                  <span>{formatBytes(items.reduce((total, file) => total + file.size_bytes, 0))}</span>
                </button>
              </div>
              <div
                className={`session-cluster-items ${collapsedUserGroups.has(group) ? 'collapsed' : ''}`}
                id={`${toDomId(group)}-memory-group`}
              >
                {items.map(file => (
                  <button
                    className={`document-card document-button memory-list-card ${
                      selected?.file_path === file.file_path && selected?.user_id === file.user_id ? 'active' : ''
                    }`}
                    key={`${file.user_id}-${file.file_path}`}
                    onClick={() => setSelected(file)}
                    type="button"
                  >
                    <div className="skill-list-card-top">
                      <strong>{file.file_path.split('/').pop()}</strong>
                      <span className="skill-policy-chip">{formatBytes(file.size_bytes)}</span>
                    </div>
                    <p>{file.file_type}</p>
                  </button>
                ))}
              </div>
            </div>
          ))}
          {files.length === 0 && <div className="empty-surface">No memory files found.</div>}
          {files.length > 0 && groupedFiles.length === 0 && <div className="empty-surface">No matching memory files.</div>}
        </div>
      </div>

      <div className="workspace-surface split-detail">
        {feedback && <div className="feedback-banner">{feedback}</div>}
        {!selected && <div className="empty-surface">Select a memory file to inspect its content.</div>}

        {selected && (
          <div className="editor-sheet">
            <div className="surface-heading">
              <span>{selected.file_path}</span>
              {canEdit && (
                <div className="button-row">
                  {!editing && (
                    <button className="action-button" onClick={() => setEditing(true)} type="button">
                      Edit
                    </button>
                  )}
                  {editing && (
                    <>
                      <button className="action-button action-button-primary" onClick={() => void saveMemory()} type="button">
                        Save
                      </button>
                      <button className="action-button" onClick={() => setEditing(false)} type="button">
                        Cancel
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>

            <div className="content-card skill-metadata-card">
              <h3>Memory Metadata</h3>
              <div className="metadata-table-shell">
                <table className="metadata-table">
                  <tbody>
                    <tr>
                      <th scope="row">User ID</th>
                      <td>
                        <code>{selected.user_id}</code>
                      </td>
                    </tr>
                    <tr>
                      <th scope="row">File Name</th>
                      <td>{selected.file_path.split('/').pop() || selected.file_path}</td>
                    </tr>
                    <tr>
                      <th scope="row">File Path</th>
                      <td>
                        <code>{selected.file_path}</code>
                      </td>
                    </tr>
                    <tr>
                      <th scope="row">Type</th>
                      <td>{selected.file_type}</td>
                    </tr>
                    <tr>
                      <th scope="row">Size</th>
                      <td>{formatBytes(selected.size_bytes)}</td>
                    </tr>
                    <tr>
                      <th scope="row">Updated</th>
                      <td>{formatDateTime(selected.modified_at)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div className="content-card">
              <h3>Memory Content</h3>
              {contentLoading && <div className="empty-surface">Loading memory content...</div>}
              {!contentLoading && editing && (
                <textarea
                  className="code-textarea"
                  onChange={event => setDraft(event.target.value)}
                  rows={18}
                  spellCheck={false}
                  value={draft}
                />
              )}
              {!contentLoading && !editing && <pre className="code-block">{content || '// Empty memory file'}</pre>}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
