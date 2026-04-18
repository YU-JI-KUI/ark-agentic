import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { NavLink, Navigate, useNavigate, useOutletContext, useParams } from 'react-router-dom'
import {
  api,
  type AgentMeta,
  type MemoryFileItem,
  type MessageItem,
  type SessionDetail,
  type SessionItem,
  type SkillMeta,
  type ToolMeta,
} from '../api'
import { useAuth } from '../auth'
import type { StudioShellContextValue } from '../layouts/StudioShell'
import { CollapseIcon, CopyIcon, ExpandIcon } from '../components/StudioIcons'

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

function toDomId(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]+/g, '-')
}

function traceLaneLabel(lane: TraceLane) {
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
  title,
  onCopy,
  onToggle,
}: {
  copied: boolean
  expanded: boolean
  title: string
  onCopy: () => void
  onToggle: () => void
}) {
  return (
    <div className="structured-data-actions">
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
}: {
  title: string
  value: string | null | undefined
  emptyText: string
  extraActions?: ReactNode
  compact?: boolean
  headingId?: string
  headingLevel?: 'h3' | 'h4'
}) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)
  const content = value && value.trim() ? value : emptyText
  const HeadingTag = headingLevel

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
          {extraActions}
          <StructuredDataControls
            copied={copied}
            expanded={expanded}
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

function daysSince(value: string | null) {
  if (!value) return Number.POSITIVE_INFINITY
  const diff = Date.now() - new Date(value).getTime()
  return Math.max(0, Math.floor(diff / (1000 * 60 * 60 * 24)))
}

function analyzeMemoryFreshness(files: MemoryFileItem[]) {
  let fresh = 0
  let aging = 0
  let stale = 0
  let unknown = 0

  for (const file of files) {
    if (!file.modified_at) {
      unknown += 1
      continue
    }
    const age = daysSince(file.modified_at)
    if (age <= 30) {
      fresh += 1
    } else if (age <= 90) {
      aging += 1
    } else {
      stale += 1
    }
  }

  const label =
    stale > 0 ? 'Needs refresh'
    : aging > 0 ? 'Aging'
    : files.length > 0 ? 'Fresh'
    : 'No memory'

  return { fresh, aging, stale, unknown, label }
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

type TraceStage = {
  lane: TraceLane
  kind: TraceEvent['kind']
  label: string
  preview: string
  accent?: string
}

type TraceTurn = {
  turn: number
  stages: TraceStage[]
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

function buildTraceTurns(detail: SessionDetail | null): TraceTurn[] {
  if (!detail) return []

  const turns: TraceTurn[] = []
  let currentTurn: TraceTurn | null = null

  function ensureTurn() {
    if (!currentTurn) {
      currentTurn = { turn: turns.length + 1, stages: [] }
      turns.push(currentTurn)
    }
    return currentTurn
  }

  function pushStage(kind: TraceEvent['kind'], label: string, preview: string, accent?: string) {
    const turn = ensureTurn()
    turn.stages.push({
      lane: laneForEvent(kind),
      kind,
      label,
      preview,
      accent,
    })
  }

  for (const message of detail.messages) {
    if (message.role === 'user' && (message.content || message.tool_calls?.length || message.tool_results?.length)) {
      currentTurn = { turn: turns.length + 1, stages: [] }
      turns.push(currentTurn)
    }

    if (message.content) {
      pushStage(
        message.role === 'user' ? 'user' : 'assistant',
        message.role === 'user' ? 'User Prompt' : 'Assistant Output',
        truncate(message.content, 180),
      )
    }

    if (message.thinking) {
      pushStage('thinking', 'Reasoning', truncate(message.thinking, 180))
    }

    for (const toolCall of message.tool_calls ?? []) {
      pushStage(
        'tool_call',
        `Tool Call · ${toolCall.name}`,
        truncate(JSON.stringify(toolCall.arguments), 180),
        'args',
      )
    }

    for (const toolResult of message.tool_results ?? []) {
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

  return turns
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

  return (
    <div className="workspace-page">
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

      {activeSection === 'overview' && <OverviewSection agent={selectedAgent} agentId={agentId} />}
      {activeSection === 'skills' && <SkillsSection agentId={agentId} />}
      {activeSection === 'tools' && <ToolsSection agentId={agentId} />}
      {activeSection === 'sessions' && <SessionsSection agentId={agentId} />}
      {activeSection === 'memory' && <MemorySection agentId={agentId} />}
    </div>
  )
}

function OverviewSection({ agent, agentId }: { agent: AgentMeta | null; agentId: string }) {
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

  const freshness = analyzeMemoryFreshness(snapshot.files)
  const reliability = analyzeToolReliability(snapshot.tools)

  return (
    <>
      <section className="workspace-grid-four">
        <div className="metric-surface">
          <span>Skills</span>
          <strong>{snapshot.skills.length}</strong>
          <p>Rules, instructions, and configuration surfaces attached to this agent.</p>
        </div>
        <div className="metric-surface">
          <span>Tools</span>
          <strong>{snapshot.tools.length}</strong>
          <p>Available tool contracts, scaffolds, and callable backend integrations.</p>
        </div>
        <div className="metric-surface">
          <span>Sessions</span>
          <strong>{snapshot.sessions.length}</strong>
          <p>Traceable session records ready for review and audit.</p>
        </div>
        <div className="metric-surface">
          <span>Knowledge Freshness</span>
          <strong>{freshness.label}</strong>
          <p>
            {freshness.fresh} fresh · {freshness.aging} aging · {freshness.stale} stale
            {freshness.unknown > 0 ? ` · ${freshness.unknown} unknown` : ''}
          </p>
        </div>
      </section>

      <section className="workspace-grid-two">
        <article className="workspace-surface">
          <div className="surface-heading">
            <span>Operational Snapshot</span>
          </div>
          <div className="signal-list">
            <div className="signal-card">
              <strong>Current agent</strong>
              <p>{agent?.description || 'No description provided for this agent.'}</p>
            </div>
            <div className="signal-card">
              <strong>Latest session activity</strong>
              <p>
                {snapshot.sessions[0]
                  ? `${snapshot.sessions[0].user_id} · ${formatRelativeTime(snapshot.sessions[0].updated_at || snapshot.sessions[0].created_at)}`
                  : 'No session activity yet.'}
              </p>
            </div>
            <div className="signal-card">
              <strong>Knowledge footprint</strong>
              <p>{snapshot.files.length} memory files currently visible to this agent.</p>
            </div>
            <div className="signal-card">
              <strong>Memory freshness signal</strong>
              <p>
                {freshness.stale > 0
                  ? `${freshness.stale} file(s) look stale based on modified time and should be reviewed first.`
                  : freshness.aging > 0
                    ? `${freshness.aging} file(s) are aging and may need content verification soon.`
                    : 'Current memory set looks fresh based on available modified timestamps.'}
              </p>
            </div>
          </div>
        </article>

        <article className="workspace-surface">
          <div className="surface-heading">
            <span>Editorial Lens</span>
          </div>
          <div className="signal-list">
            <div className="signal-card">
              <strong>Readable objects</strong>
              <p>Skills, tools, sessions, and memory each use separate layouts instead of one generic master-detail shell.</p>
            </div>
            <div className="signal-card">
              <strong>Decision-oriented AI</strong>
              <p>The dock is tuned for impact analysis, drafting, and review guidance tied to the current surface.</p>
            </div>
            <div className="signal-card">
              <strong>Tool reliability signal</strong>
              <p>
                {reliability.label} from available metadata: {reliability.documented}/{snapshot.tools.length} described,
                {` ${reliability.typed}/${snapshot.tools.length} with parsed schema.`}
              </p>
            </div>
            <div className="signal-card">
              <strong>Operational discipline</strong>
              <p>Use Overview to orient, then switch into the specific surface that owns the next change.</p>
            </div>
          </div>
        </article>
      </section>

      <section className="workspace-grid-two">
        <article className="workspace-surface">
          <div className="surface-heading">
            <span>Recent Skills</span>
          </div>
          <div className="document-list">
            {snapshot.skills.slice(0, 4).map(skill => (
              <div className="document-card" key={skill.id}>
                <strong>{skill.name}</strong>
                <p>{skill.description || skill.file_path}</p>
                <span>{skill.invocation_policy || 'manual invocation'}</span>
              </div>
            ))}
            {snapshot.skills.length === 0 && <div className="empty-surface">No skills found.</div>}
          </div>
        </article>

        <article className="workspace-surface">
          <div className="surface-heading">
            <span>Recent Tools and Memory</span>
          </div>
          <div className="document-list">
            {snapshot.tools.slice(0, 2).map(tool => (
              <div className="document-card" key={tool.name}>
                <strong>{tool.name}</strong>
                <p>{tool.description || tool.file_path}</p>
                <span>{tool.group || 'default'}</span>
              </div>
            ))}
            {snapshot.files.slice(0, 2).map(file => (
              <div className="document-card" key={`${file.user_id}-${file.file_path}`}>
                <strong>{file.file_path.split('/').pop()}</strong>
                <p>{file.file_type}</p>
                <span>{formatBytes(file.size_bytes)}</span>
              </div>
            ))}
            {snapshot.tools.length === 0 && snapshot.files.length === 0 && (
              <div className="empty-surface">No tool or memory data found.</div>
            )}
          </div>
        </article>
      </section>
    </>
  )
}

function SkillsSection({ agentId }: { agentId: string }) {
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

  const selectedSkill = useMemo(
    () => skills.find(skill => skill.id === selectedId) ?? null,
    [selectedId, skills],
  )

  const loadSkills = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextSkills = await api.listSkills(agentId)
      setSkills(nextSkills)
      setSelectedId(prev => prev ?? nextSkills[0]?.id ?? null)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError))
    } finally {
      setLoading(false)
    }
  }, [agentId])

  useEffect(() => {
    void loadSkills()
  }, [loadSkills])

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
          {canEdit && (
            <button
              className="surface-link-button"
              onClick={() => {
                setMode('create')
                setSelectedId(null)
                resetForm()
              }}
              type="button"
            >
              New Skill
            </button>
          )}
        </div>
        <div className="document-list">
          {skills.map(skill => (
            <button
              className={`document-card document-button ${selectedId === skill.id && mode === 'view' ? 'active' : ''}`}
              key={skill.id}
              onClick={() => {
                setSelectedId(skill.id)
                setMode('view')
              }}
              type="button"
            >
              <strong>{skill.name}</strong>
              <p>{skill.description || skill.file_path}</p>
              <span>{skill.invocation_policy || 'manual invocation'}</span>
            </button>
          ))}
          {skills.length === 0 && <div className="empty-surface">No skills found.</div>}
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
              <input
                onChange={event => setFormDescription(event.target.value)}
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

            <div className="workspace-grid-three">
              <div className="metric-surface">
                <span>Skill ID</span>
                <strong>{selectedSkill.id}</strong>
                <p>Persistent identifier for this skill asset.</p>
              </div>
              <div className="metric-surface">
                <span>Policy</span>
                <strong>{selectedSkill.invocation_policy || 'manual'}</strong>
                <p>Current invocation strategy exposed by backend metadata.</p>
              </div>
              <div className="metric-surface">
                <span>Group</span>
                <strong>{selectedSkill.group || 'default'}</strong>
                <p>Logical grouping used for organization and retrieval.</p>
              </div>
            </div>

            <div className="content-card">
              <h3>Description</h3>
              <p>{selectedSkill.description || 'No description provided.'}</p>
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

  const selectedTool = useMemo(
    () => tools.find(tool => tool.name === selectedName) ?? null,
    [selectedName, tools],
  )
  const reliability = useMemo(() => analyzeToolReliability(tools), [tools])

  const loadTools = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextTools = await api.listTools(agentId)
      setTools(nextTools)
      setSelectedName(prev => prev ?? nextTools[0]?.name ?? null)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError))
    } finally {
      setLoading(false)
    }
  }, [agentId])

  useEffect(() => {
    void loadTools()
  }, [loadTools])

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
          {canEdit && (
            <button
              className="surface-link-button"
              onClick={() => {
                setMode('scaffold')
                setSelectedName(null)
              }}
              type="button"
            >
              Scaffold Tool
            </button>
          )}
        </div>
        <div className="document-list">
          {tools.map(tool => (
            <button
              className={`document-card document-button ${selectedName === tool.name && mode === 'view' ? 'active' : ''}`}
              key={tool.name}
              onClick={() => {
                setSelectedName(tool.name)
                setMode('view')
              }}
              type="button"
            >
              <strong>{tool.name}</strong>
              <p>{tool.description || tool.file_path}</p>
              <span>{tool.group || 'default'}</span>
            </button>
          ))}
          {tools.length === 0 && <div className="empty-surface">No tools found.</div>}
        </div>
      </div>

      <div className="workspace-surface split-detail">
        {feedback && <div className="feedback-banner">{feedback}</div>}
        <div className="workspace-grid-three">
          <div className="metric-surface">
            <span>Total Tools</span>
            <strong>{tools.length}</strong>
            <p>Declared tool surfaces available to this agent.</p>
          </div>
          <div className="metric-surface">
            <span>Reliability Signal</span>
            <strong>{reliability.label}</strong>
            <p>Inferred from descriptions and parsed parameter schema coverage.</p>
          </div>
          <div className="metric-surface">
            <span>Metadata Coverage</span>
            <strong>{reliability.score}%</strong>
            <p>{reliability.documented} described · {reliability.typed} with schema.</p>
          </div>
        </div>

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
            <div className="workspace-grid-three">
              <div className="metric-surface">
                <span>Group</span>
                <strong>{selectedTool.group || 'default'}</strong>
                <p>Grouping metadata for this tool definition.</p>
              </div>
              <div className="metric-surface">
                <span>Source File</span>
                <strong>{selectedTool.file_path}</strong>
                <p>Workspace location where the scaffolded implementation lives.</p>
              </div>
              <div className="metric-surface">
                <span>Description</span>
                <strong>{selectedTool.description || 'n/a'}</strong>
                <p>Operator-facing summary of tool purpose.</p>
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
  const [query, setQuery] = useState('')
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [rawText, setRawText] = useState('')
  const [rawDraft, setRawDraft] = useState('')
  const [tab, setTab] = useState<'conversation' | 'trace' | 'raw'>('conversation')
  const [editingRaw, setEditingRaw] = useState(false)
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
        if (tab === 'conversation' || tab === 'trace') {
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

  const traceTurns = buildTraceTurns(detail)
  const traceEvents = traceTurns.flatMap(turn => turn.stages)
  const toolCalls = traceEvents.filter(event => event.kind === 'tool_call').length
  const toolResults = traceEvents.filter(event => event.kind === 'tool_result').length
  const reasoningSteps = traceEvents.filter(event => event.kind === 'thinking').length
  const outputSteps = traceEvents.filter(event => event.kind === 'assistant').length
  const filteredSessionCount = groupedSessions.reduce((total, [, items]) => total + items.length, 0)
  const sessionDomId = selected ? toDomId(selected.session_id) : 'session'
  const conversationTabId = `${sessionDomId}-conversation-tab`
  const traceTabId = `${sessionDomId}-trace-tab`
  const rawTabId = `${sessionDomId}-raw-tab`
  const conversationPanelId = `${sessionDomId}-conversation-panel`
  const tracePanelId = `${sessionDomId}-trace-panel`
  const rawPanelId = `${sessionDomId}-raw-panel`

  return (
    <section className="workspace-split workspace-sessions">
      <div className="workspace-surface split-list session-nav-panel">
        <div className="surface-heading">
          <span>Sessions</span>
          <span>{filteredSessionCount}</span>
        </div>
        <div className="session-nav-intro">
          <strong>Traceable conversation index</strong>
          <p>Filter by user, session id, or first message to jump directly into the right evidence trail.</p>
        </div>
        <label className="session-search">
          <input
            aria-label="Search sessions"
            onChange={event => setQuery(event.target.value)}
            placeholder="Search sessions"
            value={query}
          />
        </label>
        <div aria-label="Sessions" className="session-nav-list" role="listbox">
          {groupedSessions.map(([userId, items]) => (
            <div className="session-cluster" key={userId}>
              <div className="session-cluster-head">
                <div className="session-group-title">{userId}</div>
                <span>{items.length}</span>
              </div>
              {items.map(session => (
                <button
                  aria-label={`Session ${session.first_message || session.session_id}`}
                  aria-selected={selected?.session_id === session.session_id}
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
                  role="option"
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
          ))}
          {filteredSessionCount === 0 && <div className="empty-surface">No sessions found.</div>}
        </div>
      </div>

      <div className="workspace-surface split-detail session-detail-panel">
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
            <div className="session-detail-hero">
              <div className="session-detail-hero-copy">
                <div className="surface-kicker">Session Detail</div>
                <h2>{selected.first_message || selected.session_id}</h2>
                <p>{selected.session_id}</p>
              </div>
              <div aria-label="Session detail views" className="session-mode-switch" role="tablist">
                <button
                  aria-controls={conversationPanelId}
                  aria-selected={tab === 'conversation'}
                  className={`action-button ${tab === 'conversation' ? 'action-button-primary' : ''}`}
                  id={conversationTabId}
                  onFocus={() => setTab('conversation')}
                  onClick={() => setTab('conversation')}
                  role="tab"
                  type="button"
                >
                  Conversation
                </button>
                <button
                  aria-controls={tracePanelId}
                  aria-selected={tab === 'trace'}
                  className={`action-button ${tab === 'trace' ? 'action-button-primary' : ''}`}
                  id={traceTabId}
                  onFocus={() => setTab('trace')}
                  onClick={() => setTab('trace')}
                  role="tab"
                  type="button"
                >
                  Trace
                </button>
                <button
                  aria-controls={rawPanelId}
                  aria-selected={tab === 'raw'}
                  className={`action-button ${tab === 'raw' ? 'action-button-primary' : ''}`}
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

            <div className="workspace-grid-three">
              <div className="metric-surface">
                <span>User ID</span>
                <strong>{selected.user_id}</strong>
                <p>Session ownership used by Studio session APIs.</p>
              </div>
              <div className="metric-surface">
                <span>Messages</span>
                <strong>{selected.message_count}</strong>
                <p>Total message records counted by the backend.</p>
              </div>
              <div className="metric-surface">
                <span>Updated</span>
                <strong>{formatRelativeTime(selected.updated_at || selected.created_at)}</strong>
                <p>Useful for triaging recent operational activity.</p>
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
                      key={`${message.role}-${index}`}
                      message={message}
                      messageIndex={index}
                    />
                  ))}
                </div>
              </div>
            )}

            {!detailLoading && tab === 'trace' && detail && (
              <div
                aria-labelledby={traceTabId}
                className="editor-sheet"
                id={tracePanelId}
                role="tabpanel"
              >
                <div className="workspace-grid-three">
                  <div className="metric-surface">
                    <span>Trace Turns</span>
                    <strong>{traceTurns.length}</strong>
                    <p>Grouped by user prompt boundaries to show end-to-end execution flow.</p>
                  </div>
                  <div className="metric-surface">
                    <span>Tool Execution</span>
                    <strong>{toolCalls}/{toolResults}</strong>
                    <p>Detected tool calls and returned results in this session.</p>
                  </div>
                  <div className="metric-surface">
                    <span>Model Steps</span>
                    <strong>{reasoningSteps + outputSteps}</strong>
                    <p>{reasoningSteps} reasoning blocks and {outputSteps} assistant outputs.</p>
                  </div>
                </div>
                <div className="trace-legend">
                  <span>Input</span>
                  <span>Reasoning</span>
                  <span>Tools</span>
                  <span>Output</span>
                  <span>Metadata</span>
                </div>
                <section aria-label="Session trace execution flow" className="trace-board">
                  {traceTurns.map(traceTurn => (
                    <section
                      aria-labelledby={`${sessionDomId}-trace-turn-${traceTurn.turn}`}
                      className="trace-turn"
                      key={traceTurn.turn}
                    >
                      <div className="trace-turn-header">
                        <h3 className="trace-turn-badge" id={`${sessionDomId}-trace-turn-${traceTurn.turn}`}>
                          Turn {traceTurn.turn}
                        </h3>
                        <p>{traceTurn.stages.length} stage(s) inferred from recorded session messages.</p>
                      </div>
                      <div className="trace-lane-grid">
                        {(['input', 'reasoning', 'tools', 'output', 'metadata'] as TraceLane[]).map(lane => {
                          const stages = traceTurn.stages.filter(stage => stage.lane === lane)
                          return (
                            <section
                              aria-labelledby={`${sessionDomId}-trace-turn-${traceTurn.turn}-${lane}`}
                              className={`trace-lane trace-lane-${lane}`}
                              key={`${traceTurn.turn}-${lane}`}
                            >
                              <h4
                                className="trace-lane-title"
                                id={`${sessionDomId}-trace-turn-${traceTurn.turn}-${lane}`}
                              >
                                {traceLaneLabel(lane)}
                              </h4>
                              {stages.length > 0 ? (
                                stages.map((stage, index) => (
                                  <div
                                    className={`trace-node trace-${stage.kind} ${stage.accent ? `trace-accent-${stage.accent}` : ''}`}
                                    key={`${traceTurn.turn}-${lane}-${index}`}
                                  >
                                    <strong>{stage.label}</strong>
                                    <p>{stage.preview}</p>
                                  </div>
                                ))
                              ) : (
                                <div className="trace-node trace-node-empty">
                                  <strong>No event</strong>
                                  <p>No recorded data for this lane in the current turn.</p>
                                </div>
                              )}
                            </section>
                          )
                        })}
                      </div>
                    </section>
                  ))}
                  {traceTurns.length === 0 && (
                    <div className="empty-surface">No traceable events were derived from this session.</div>
                  )}
                </section>
                <div className="content-card">
                  <h3>Trace Notes</h3>
                  <p>
                    This execution chain is inferred from stored session detail, not from a dedicated span-tracing backend.
                    It is still useful for understanding prompt, reasoning, tool usage, output, and metadata flow per turn.
                  </p>
                </div>
              </div>
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

function SessionMessageCard({ message, messageIndex }: { message: MessageItem; messageIndex: number }) {
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
  const { user } = useAuth()
  const canEdit = user?.role === 'editor'
  const [files, setFiles] = useState<MemoryFileItem[]>([])
  const [selected, setSelected] = useState<MemoryFileItem | null>(null)
  const [content, setContent] = useState('')
  const [draft, setDraft] = useState('')
  const [editing, setEditing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [contentLoading, setContentLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)

  const groupedFiles = useMemo(() => {
    const next = new Map<string, MemoryFileItem[]>()
    for (const file of files) {
      const key = file.user_id || '(global)'
      const list = next.get(key) ?? []
      list.push(file)
      next.set(key, list)
    }
    return [...next.entries()]
  }, [files])
  const freshness = useMemo(() => analyzeMemoryFreshness(files), [files])

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const nextFiles = await api.listMemoryFiles(agentId)
        if (!cancelled) {
          setFiles(nextFiles)
          setSelected(nextFiles[0] ?? null)
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
        <div className="document-list">
          {groupedFiles.map(([group, items]) => (
            <div className="session-group" key={group}>
              <div className="session-group-title">{group}</div>
              {items.map(file => (
                <button
                  className={`document-card document-button ${
                    selected?.file_path === file.file_path && selected?.user_id === file.user_id ? 'active' : ''
                  }`}
                  key={`${file.user_id}-${file.file_path}`}
                  onClick={() => setSelected(file)}
                  type="button"
                >
                  <strong>{file.file_path.split('/').pop()}</strong>
                  <p>{file.file_type}</p>
                  <span>{formatBytes(file.size_bytes)}</span>
                </button>
              ))}
            </div>
          ))}
          {files.length === 0 && <div className="empty-surface">No memory files found.</div>}
        </div>
      </div>

      <div className="workspace-surface split-detail">
        {feedback && <div className="feedback-banner">{feedback}</div>}
        <div className="workspace-grid-three">
          <div className="metric-surface">
            <span>Memory Freshness</span>
            <strong>{freshness.label}</strong>
            <p>Estimated from `modified_at` timestamps exposed by the backend.</p>
          </div>
          <div className="metric-surface">
            <span>Fresh / Aging</span>
            <strong>{freshness.fresh}/{freshness.aging}</strong>
            <p>Files updated within 30 days vs 31-90 days.</p>
          </div>
          <div className="metric-surface">
            <span>Stale / Unknown</span>
            <strong>{freshness.stale}/{freshness.unknown}</strong>
            <p>Files older than 90 days or without timestamp metadata.</p>
          </div>
        </div>
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

            <div className="workspace-grid-three">
              <div className="metric-surface">
                <span>Type</span>
                <strong>{selected.file_type}</strong>
                <p>Memory classification exposed by the backend.</p>
              </div>
              <div className="metric-surface">
                <span>Size</span>
                <strong>{formatBytes(selected.size_bytes)}</strong>
                <p>Current memory file size before any manual edits.</p>
              </div>
              <div className="metric-surface">
                <span>Modified</span>
                <strong>{selected.modified_at ? formatRelativeTime(selected.modified_at) : 'unknown'}</strong>
                <p>Last modification timestamp when available.</p>
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
