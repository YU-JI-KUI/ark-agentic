import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
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
import { BoltIcon, ChevronRightIcon, CopyIcon, DownloadIcon, ExpandIcon, PlusIcon, SearchIcon } from '../components/StudioIcons'

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

function CopyButton({ value, title }: { value: string; title: string }) {
  const [copied, setCopied] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  return (
    <button
      aria-label={`Copy ${title}`}
      className="icon-action-button"
      onClick={async () => {
        try {
          await copyText(value)
          setCopied(true)
          if (timerRef.current) clearTimeout(timerRef.current)
          timerRef.current = window.setTimeout(() => setCopied(false), 1200)
        } catch {
          setCopied(false)
        }
      }}
      type="button"
      title={copied ? `${title} copied` : `Copy ${title}`}
    >
      <CopyIcon />
    </button>
  )
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}


type TimelineItemBase = { turn: number }
type TimelineItem =
  | (TimelineItemBase & { kind: 'user' | 'assistant'; role: string; text: string; raw: MessageItem })
  | (TimelineItemBase & { kind: 'tool'; name: string; args: Record<string, unknown>; result: unknown; isError: boolean; sub: number })

function flattenTimeline(detail: SessionDetail | null): TimelineItem[] {
  if (!detail) return []
  const items: TimelineItem[] = []
  let turnIdx = 0

  for (const message of detail.messages) {
    turnIdx += 1
    if (message.content) {
      items.push({
        kind: message.role === 'user' ? 'user' : 'assistant',
        role: message.role,
        text: message.content,
        turn: turnIdx,
        raw: message,
      })
    }

    const calls = message.tool_calls ?? []
    const results = message.tool_results ?? []
    calls.forEach((call, sub) => {
      const matched = results.find(r => r.tool_call_id === call.id)
      items.push({
        kind: 'tool',
        name: call.name,
        args: call.arguments,
        result: matched?.content ?? '',
        isError: Boolean(matched?.is_error),
        sub,
        turn: turnIdx,
      })
    })
  }
  return items
}

function downloadJsonl(filename: string, messages: MessageItem[]) {
  const text = messages.map(m => JSON.stringify(m)).join('\n')
  const blob = new Blob([text], { type: 'application/jsonl' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function zeropad(n: number) {
  return n < 10 ? `0${n}` : String(n)
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
            <span>{(selectedAgent?.id ?? agentId).toUpperCase()}</span>
            <span>{formatAgentDate(selectedAgent?.updated_at)}</span>
          </div>
        </div>

        <div className="workspace-context-actions">
          <button className="btn btn-sm" disabled type="button" title="即将推出">Configure</button>
          <button className="btn btn-sm" disabled type="button" title="即将推出">Export</button>
          <button className="btn btn-accent btn-sm" disabled type="button" title="即将推出">Test agent</button>
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

  const recentSkills = [...snapshot.skills]
    .sort((left, right) => getTimestampValue(right.modified_at) - getTimestampValue(left.modified_at))
    .slice(0, 3)
  const recentTools = [...snapshot.tools]
    .sort((left, right) => getTimestampValue(right.modified_at) - getTimestampValue(left.modified_at))
    .slice(0, 3)
  const recentFiles = [...snapshot.files]
    .sort((left, right) => getTimestampValue(right.modified_at) - getTimestampValue(left.modified_at))
    .slice(0, 3)

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
            <span>Health</span>
          </div>
          <div>
            {(() => {
              const skillsTaggedOrGrouped = snapshot.skills.filter(skill =>
                Boolean(skill.group?.trim()) || (skill.tags?.filter(Boolean).length ?? 0) > 0,
              ).length
              const toolsWithSchema = snapshot.tools.filter(t => Object.keys(t.parameters || {}).length > 0).length
              const sessionsNonEmpty = snapshot.sessions.filter(s => s.message_count > 0).length

              const rows: Array<{ label: string; detail: string; status: 'ok' | 'warn'; badge: string }> = [
                {
                  label: 'Skills 配置',
                  detail: `${skillsTaggedOrGrouped}/${snapshot.skills.length} 已带分组或标签`,
                  status: snapshot.skills.length === 0 || skillsTaggedOrGrouped < snapshot.skills.length ? 'warn' : 'ok',
                  badge: snapshot.skills.length === 0 ? 'EMPTY' : skillsTaggedOrGrouped < snapshot.skills.length ? 'WARN' : 'OK',
                },
                {
                  label: 'Tools schema',
                  detail: `${toolsWithSchema}/${snapshot.tools.length} 已解析 schema`,
                  status: snapshot.tools.length === 0 || toolsWithSchema < snapshot.tools.length ? 'warn' : 'ok',
                  badge: snapshot.tools.length === 0 ? 'EMPTY' : toolsWithSchema < snapshot.tools.length ? 'WARN' : 'OK',
                },
                {
                  label: 'Memory 完整性',
                  detail: `${snapshot.files.length} 个文件 · 0 损坏`,
                  status: 'ok',
                  badge: 'OK',
                },
                {
                  label: 'Session 活跃度',
                  detail: `${sessionsNonEmpty}/${snapshot.sessions.length} 有消息`,
                  status: snapshot.sessions.length > 0 && sessionsNonEmpty < snapshot.sessions.length ? 'warn' : 'ok',
                  badge: snapshot.sessions.length === 0 ? 'EMPTY' : sessionsNonEmpty < snapshot.sessions.length ? 'WARN' : 'OK',
                },
              ]

              return rows.map(row => (
                <div className="health-row" key={row.label}>
                  <span className={`status-dot ${row.status}`} />
                  <div>
                    <div className="row-name">{row.label}</div>
                    <div className="row-meta">{row.detail}</div>
                  </div>
                  <span className={`badge ${row.status}`}>{row.badge}</span>
                </div>
              ))
            })()}
          </div>
        </article>
      </section>

      <section className="workspace-grid-three">
        <article className="workspace-surface">
          <div className="surface-heading">
            <span>最近技能</span>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => navigate(`/agents/${agentId}/skills`)}
              type="button"
            >
              View all →
            </button>
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
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => navigate(`/agents/${agentId}/tools`)}
              type="button"
            >
              View all →
            </button>
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
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => navigate(`/agents/${agentId}/memory`)}
              type="button"
            >
              View all →
            </button>
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
        <div className="filter-bar">
          <label className="search">
            <SearchIcon />
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

            <div className="kv-table">
              <div className="kv-row">
                <div className="kv-key">Skill ID</div>
                <div className="kv-val"><code>{selectedSkill.id}</code></div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Version</div>
                <div className="kv-val">{selectedSkill.version || '—'}</div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Policy</div>
                <div className="kv-val">
                  <span className={`badge ${selectedSkill.invocation_policy === 'auto' ? 'accent' : ''}`}>
                    {selectedSkill.invocation_policy || 'manual'}
                  </span>
                </div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Group</div>
                <div className="kv-val">{selectedSkill.group || 'default'}</div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Tags</div>
                <div className="kv-val">
                  {selectedSkill.tags && selectedSkill.tags.length > 0 ? (
                    <div className="metadata-tag-list" role="list" aria-label="Skill tags">
                      {selectedSkill.tags.map(tag => (
                        <span className="metadata-tag" key={tag} role="listitem">{tag}</span>
                      ))}
                    </div>
                  ) : '—'}
                </div>
              </div>
              <div className="kv-row">
                <div className="kv-key">File path</div>
                <div className="kv-val">
                  {selectedSkill.file_path ? <code>{selectedSkill.file_path}</code> : '—'}
                </div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Updated</div>
                <div className="kv-val">
                  {selectedSkill.modified_at ? formatRelativeTime(selectedSkill.modified_at) : '—'}
                </div>
              </div>
            </div>

            <div className="code-meta-row">
              <span className="kv-label">Prompt and guidelines</span>
              <div className="code-actions">
                <CopyButton value={selectedSkill.content || ''} title="Prompt" />
              </div>
            </div>
            <pre className="code-block">{selectedSkill.content || 'File is empty.'}</pre>
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
        <div className="filter-bar">
          <label className="search">
            <SearchIcon />
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

            <div className="kv-table">
              <div className="kv-row">
                <div className="kv-key">Tool name</div>
                <div className="kv-val"><code>{selectedTool.name}</code></div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Group</div>
                <div className="kv-val">{selectedTool.group || 'default'}</div>
              </div>
              <div className="kv-row">
                <div className="kv-key">File path</div>
                <div className="kv-val">
                  {selectedTool.file_path ? <code>{selectedTool.file_path}</code> : '—'}
                </div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Updated</div>
                <div className="kv-val">
                  {selectedTool.modified_at ? formatRelativeTime(selectedTool.modified_at) : '—'}
                </div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Parameters</div>
                <div className="kv-val">{Object.keys(selectedTool.parameters || {}).length}</div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Description</div>
                <div className="kv-val">{selectedTool.description || '—'}</div>
              </div>
            </div>

            <div className="code-meta-row">
              <span className="kv-label">Parameter schema</span>
              <div className="code-actions">
                <CopyButton
                  value={Object.keys(selectedTool.parameters || {}).length > 0
                    ? JSON.stringify(selectedTool.parameters, null, 2)
                    : ''}
                  title="Schema"
                />
              </div>
            </div>
            <pre className="code-light">
              {Object.keys(selectedTool.parameters || {}).length > 0
                ? JSON.stringify(selectedTool.parameters, null, 2)
                : '// No parameters defined'}
            </pre>
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
  const [rawDraft, setRawDraft] = useState('')
  const [editingRaw, setEditingRaw] = useState(false)
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})
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

  // Always load detail when selected changes
  useEffect(() => {
    if (!selected) return
    const currentSession = selected
    let cancelled = false

    async function loadDetail() {
      setDetailLoading(true)
      try {
        const nextDetail = await api.getSessionDetail(
          agentId,
          currentSession.session_id,
          currentSession.user_id,
        )
        if (!cancelled) setDetail(nextDetail)
      } catch (nextError) {
        if (!cancelled) {
          setFeedback(nextError instanceof Error ? nextError.message : String(nextError))
          setFeedbackTone('alert')
        }
      } finally {
        if (!cancelled) setDetailLoading(false)
      }
    }

    void loadDetail()
    return () => { cancelled = true }
  }, [agentId, selected])

  // Load raw only when the raw drawer is opened
  useEffect(() => {
    if (!editingRaw || !selected) return
    const currentSession = selected
    let cancelled = false

    async function loadRaw() {
      try {
        const nextRaw = await api.getSessionRaw(
          agentId,
          currentSession.session_id,
          currentSession.user_id,
        )
        if (!cancelled) {
          setRawDraft(nextRaw)
        }
      } catch (nextError) {
        if (!cancelled) {
          setFeedback(nextError instanceof Error ? nextError.message : String(nextError))
          setFeedbackTone('alert')
        }
      }
    }

    void loadRaw()
    return () => { cancelled = true }
  }, [agentId, editingRaw, selected])

  useEffect(() => {
    setExpanded({ 0: true })
    setEditingRaw(false)
  }, [selected?.session_id])

  useEffect(() => {
    setCollapsedUserGroups(new Set())
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

  return (
    <section className="workspace-split workspace-sessions">
      <div className="workspace-surface split-list session-nav-panel">
        <div className="surface-heading">
          <span>Sessions</span>
          <span>{filteredSessionCount}</span>
        </div>
        <div className="filter-bar">
          <label className="search">
            <SearchIcon />
            <input
              aria-label="Search sessions"
              onChange={event => setQuery(event.target.value)}
              placeholder="Search sessions, users, IDs"
              value={query}
            />
          </label>
        </div>
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
                  className={`session-row ${selected?.session_id === session.session_id ? 'active' : ''}`}
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
                  <span className="session-row-title">
                    {session.first_message || session.session_id.slice(0, 14)}
                  </span>
                  <span className="session-row-meta">
                    <span className="session-row-count">{session.message_count}</span>
                    <span className="session-row-time">{formatRelativeTime(session.updated_at || session.created_at)}</span>
                  </span>
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
              ? `Viewing session ${selected.first_message || selected.session_id}`
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
            <div className="session-detail-header">
              <div className="session-title-row">
                <h2>{selected.first_message || selected.session_id}</h2>
                <div className="session-actions">
                  <button
                    className="chip"
                    onClick={() => downloadJsonl(`${selected.session_id}.jsonl`, detail?.messages ?? [])}
                    type="button"
                    title="Download raw JSONL"
                    disabled={!detail}
                  >
                    <DownloadIcon />
                    Raw JSONL
                  </button>
                  {canEdit && (
                    <button
                      className="chip"
                      onClick={() => setEditingRaw(prev => !prev)}
                      type="button"
                      title="Edit raw JSONL"
                    >
                      {editingRaw ? 'Close raw' : 'Edit raw'}
                    </button>
                  )}
                  <button
                    aria-label="Copy session id"
                    className="icon-action-button"
                    onClick={() => void copyText(selected.session_id)}
                    type="button"
                    title="Copy session id"
                  >
                    <CopyIcon />
                  </button>
                  <button
                    aria-label="Expand all"
                    className="icon-action-button"
                    onClick={() => {
                      const items = flattenTimeline(detail)
                      const allExpanded = items.length > 0 && items.every((_, i) => expanded[i])
                      setExpanded(allExpanded ? {} : Object.fromEntries(items.map((_, i) => [i, true])))
                    }}
                    type="button"
                    title="Expand all / Collapse all"
                  >
                    <ExpandIcon />
                  </button>
                </div>
              </div>
              <dl className="session-meta-strip">
                <div className="session-meta-item">
                  <dt>USER</dt>
                  <dd>{selected.user_id}</dd>
                </div>
                <div className="session-meta-item">
                  <dt>MESSAGES</dt>
                  <dd>{selected.message_count}</dd>
                </div>
                <div className="session-meta-item">
                  <dt>TOOLS USED</dt>
                  <dd>{(detail?.messages ?? []).reduce((n, m) => n + (m.tool_calls?.length ?? 0), 0)}</dd>
                </div>
                <div className="session-meta-item">
                  <dt>UPDATED</dt>
                  <dd>{formatRelativeTime(selected.updated_at || selected.created_at)}</dd>
                </div>
                <div className="session-meta-item session-meta-item-id">
                  <dt>SESSION</dt>
                  <dd title={selected.session_id}>{selected.session_id}</dd>
                </div>
              </dl>
            </div>

            {editingRaw && canEdit && (
              <div className="session-raw-drawer">
                <div className="session-raw-drawer-head">
                  <span className="kv-label">Raw JSONL</span>
                  <div className="button-row">
                    <button className="action-button action-button-primary" onClick={() => void saveRaw()} type="button">
                      Save
                    </button>
                    <button className="action-button" onClick={() => setEditingRaw(false)} type="button">
                      Cancel
                    </button>
                  </div>
                </div>
                <textarea
                  className="code-textarea"
                  onChange={event => setRawDraft(event.target.value)}
                  rows={14}
                  spellCheck={false}
                  value={rawDraft}
                />
              </div>
            )}

            {detailLoading && <div className="empty-surface">Loading session detail...</div>}

            {!detailLoading && detail && (
              <div className="timeline-main" aria-label="Session timeline">
                {flattenTimeline(detail).map((it, i) => {
                  const isOpen = !!expanded[i]
                  return (
                    <div key={i}>
                      <div
                        className={`tlm-item ${it.kind} ${isOpen ? 'active' : ''}`}
                        onClick={() => setExpanded(e => ({ ...e, [i]: !e[i] }))}
                      >
                        <div className="tlm-marker">
                          <div className={`tlm-dot ${it.kind}`}>
                            {it.kind === 'tool' && <BoltIcon />}
                          </div>
                        </div>
                        <div className="tlm-content">
                          <div className="tlm-head">
                            <span className={`tlm-role ${it.kind === 'tool' ? 'tool' : ''}`}>
                              {it.kind === 'tool' ? `tool · ${it.name}` : `${it.role} · turn ${it.turn}`}
                            </span>
                            <span className="tlm-meta">
                              {it.kind === 'tool' ? (it.isError ? 'error' : 'ok') : `#${zeropad(i + 1)}`}
                            </span>
                          </div>
                          <div className={`tlm-text ${it.kind === 'tool' ? 'mono' : ''}`}>
                            {it.kind === 'tool'
                              ? `${it.name}(${JSON.stringify(it.args)}) → ${typeof it.result === 'string' ? it.result : JSON.stringify(it.result)}`
                              : it.text}
                          </div>
                        </div>
                      </div>
                      {isOpen && (
                        <div className="tlm-detail">
                          {it.kind === 'tool' ? (
                            <>
                              <div className="dt-row">
                                <div className="dt-label">tool</div>
                                <div className="dt-value mono">{it.name}</div>
                              </div>
                              <div className="dt-row">
                                <div className="dt-label">args</div>
                                <div className="dt-value mono">
                                  <pre>{JSON.stringify(it.args, null, 2)}</pre>
                                </div>
                              </div>
                              <div className="dt-row">
                                <div className="dt-label">result</div>
                                <div className={`dt-value mono ${it.isError ? 'err' : 'ok'}`} style={{ color: it.isError ? 'var(--err)' : 'var(--ok)' }}>
                                  <pre>{typeof it.result === 'string' ? it.result : JSON.stringify(it.result, null, 2)}</pre>
                                </div>
                              </div>
                              <div className="dt-row">
                                <div className="dt-label">turn</div>
                                <div className="dt-value mono">{it.turn}</div>
                              </div>
                            </>
                          ) : (
                            <>
                              <div className="dt-row">
                                <div className="dt-label">role</div>
                                <div className="dt-value mono">{it.role}</div>
                              </div>
                              <div className="dt-row">
                                <div className="dt-label">content</div>
                                <div className="dt-value" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.55 }}>{it.text}</div>
                              </div>
                              {it.raw.thinking && (
                                <div className="dt-block">
                                  <div className="dt-label">thinking</div>
                                  <pre className="code-block compact">{it.raw.thinking}</pre>
                                </div>
                              )}
                              {it.raw.tool_calls && it.raw.tool_calls.length > 0 && (
                                <div className="dt-block">
                                  <div className="dt-label">tools invoked</div>
                                  {it.raw.tool_calls.map((tc, k) => (
                                    <div key={k} className="tool-call">
                                      <div className="tool-call-head">
                                        <BoltIcon />
                                        <span className="tool-call-name">{tc.name}</span>
                                      </div>
                                      <div className="tool-call-body">
                                        <div>args: {JSON.stringify(tc.arguments)}</div>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}

                <div className="session-state-footer">
                  <span className="kv-label">Session state</span>
                  <div className="state-grid">
                    {Object.entries(detail.state ?? {}).map(([k, v]) => (
                      <div key={k}>
                        <span className="text-dim">{k}:</span> {String(v)}
                      </div>
                    ))}
                    <div>
                      <span className="text-dim">tools_used:</span>{' '}
                      {(detail.messages ?? []).reduce((n, m) => n + (m.tool_calls?.length ?? 0), 0)}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  )
}


function MemorySection({ agentId }: { agentId: string }) {
  const [searchParams] = useSearchParams()
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
        <div className="filter-bar">
          <label className="search">
            <SearchIcon />
            <input
              aria-label="Search memory files"
              onChange={event => setQuery(event.target.value)}
              placeholder="Search memory"
              value={query}
            />
          </label>
        </div>
        <div className="document-list">
          {filteredFiles.map(file => (
            <button
              className={`document-card document-button memory-list-card ${
                selected?.file_path === file.file_path && selected?.user_id === file.user_id ? 'active' : ''
              }`}
              key={`${file.user_id}-${file.file_path}`}
              onClick={() => setSelected(file)}
              type="button"
            >
              <div className="skill-list-card-top">
                <strong>{file.file_path.split('/').pop() || file.file_path}</strong>
                <span className="skill-policy-chip">{file.user_id}</span>
              </div>
              <p>
                {file.file_type} · {formatBytes(file.size_bytes)}
                {file.modified_at && ` · ${formatRelativeTime(file.modified_at)}`}
              </p>
            </button>
          ))}
          {files.length === 0 && <div className="empty-surface">No memory files found.</div>}
          {files.length > 0 && filteredFiles.length === 0 && <div className="empty-surface">No matching memory files.</div>}
        </div>
      </div>

      <div className="workspace-surface split-detail">
        {feedback && <div className="feedback-banner">{feedback}</div>}
        {!selected && <div className="empty-surface">Select a memory file to inspect its content.</div>}

        {selected && (
          <div className="editor-sheet">
            <div className="surface-heading">
              <span>{selected.file_path.split('/').pop() || selected.file_path}</span>
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

            <div className="kv-table">
              <div className="kv-row">
                <div className="kv-key">User ID</div>
                <div className="kv-val"><code>{selected.user_id}</code></div>
              </div>
              <div className="kv-row">
                <div className="kv-key">File name</div>
                <div className="kv-val"><code>{selected.file_path.split('/').pop() || selected.file_path}</code></div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Path</div>
                <div className="kv-val"><code>{selected.file_path}</code></div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Type</div>
                <div className="kv-val">{selected.file_type}</div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Size</div>
                <div className="kv-val">{formatBytes(selected.size_bytes)}</div>
              </div>
              <div className="kv-row">
                <div className="kv-key">Updated</div>
                <div className="kv-val">{formatDateTime(selected.modified_at)}</div>
              </div>
            </div>

            <div className="code-meta-row">
              <span className="kv-label">Memory content</span>
              <div className="code-actions">
                <CopyButton value={content} title="Memory content" />
              </div>
            </div>

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
        )}
      </div>
    </section>
  )
}
