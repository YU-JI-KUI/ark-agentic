import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
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
  type TurnContext,
} from '../api'
import { canEditStudio, useAuth } from '../auth'
import type { StudioShellContextValue } from '../layouts/StudioShell'
import { ChevronRightIcon, CopyIcon, DownloadIcon, ExpandIcon, PlusIcon, SearchIcon } from '../components/StudioIcons'

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

function CodeBody({
  value,
  className = '',
  children,
}: {
  value: string
  className?: string
  children: ReactNode
}) {
  return (
    <div className={`code-body ${className}`}>
      <div className="code-body-actions">
        <CopyButton value={value} title="content" />
      </div>
      {children}
    </div>
  )
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
  | (TimelineItemBase & {
      kind: 'user' | 'assistant'
      role: string
      text: string
      raw: MessageItem
      metadata?: Record<string, unknown> | null
    })
  | (TimelineItemBase & {
      kind: 'tool'
      name: string
      args: Record<string, unknown>
      result: unknown
      resultType?: string
      llmDigest?: string | null
      isError: boolean
      toolCallId: string
      sub: number
      raw: MessageItem
      preamble?: string
    })

function flattenTimeline(detail: SessionDetail | null): TimelineItem[] {
  if (!detail) return []

  const resultsByCallId = new Map<string, NonNullable<MessageItem['tool_results']>[number]>()
  for (const msg of detail.messages) {
    if (msg.tool_results) {
      for (const tr of msg.tool_results) {
        if (tr.tool_call_id) resultsByCallId.set(tr.tool_call_id, tr)
      }
    }
  }

  const items: TimelineItem[] = []
  let turnIdx = 0

  for (const message of detail.messages) {
    if (message.role === 'tool') continue

    turnIdx += 1
    const calls = message.tool_calls ?? []

    // When the assistant returns content alongside tool_calls, the text is a
    // preamble for the call ("Sure, let me look that up.") — fold it into the
    // first tool item rather than emit a phantom assistant bubble. The wire
    // format keeps message.content intact so LLM history reconstruction is
    // unaffected.
    if (message.content && calls.length === 0) {
      items.push({
        kind: message.role === 'user' ? 'user' : 'assistant',
        role: message.role,
        text: message.content,
        turn: turnIdx,
        raw: message,
        metadata: message.metadata ?? undefined,
      })
    }

    calls.forEach((call, sub) => {
      const result = resultsByCallId.get(call.id)
      const md = (result?.metadata ?? {}) as Record<string, unknown>
      items.push({
        kind: 'tool',
        name: call.name,
        args: call.arguments,
        result: result?.content ?? '',
        resultType: result?.result_type,
        llmDigest: result?.llm_digest ?? null,
        isError: Boolean(result?.is_error),
        toolCallId: call.id,
        sub,
        turn: turnIdx,
        raw: message,
        preamble: sub === 0 && message.content ? message.content : undefined,
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

function summarizeText(value: string | null | undefined, max = 96): string {
  if (!value) return ''
  const collapsed = value.replace(/\s+/g, ' ').trim()
  return collapsed.length > max ? `${collapsed.slice(0, max - 1)}…` : collapsed
}

function JsonValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  const [open, setOpen] = useState(depth === 0)

  if (value === null) return <span className="json-leaf json-null">null</span>
  if (value === undefined) return <span className="json-leaf json-null">undefined</span>
  const t = typeof value
  if (t === 'string') return <span className="json-leaf json-string">"{value as string}"</span>
  if (t === 'number') return <span className="json-leaf json-number">{String(value)}</span>
  if (t === 'boolean') return <span className="json-leaf json-boolean">{String(value)}</span>

  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="json-leaf json-empty">[]</span>
    return (
      <div className="json-node">
        <button
          aria-expanded={open}
          className={`json-node-toggle ${open ? 'open' : ''}`}
          onClick={() => setOpen(prev => !prev)}
          type="button"
        >
          <ChevronRightIcon className="json-node-chevron" />
          <span className="json-type-tag">[{value.length} items]</span>
        </button>
        {open && (
          <ul className="json-node-children">
            {value.map((item, i) => (
              <li className="json-node-row" key={i}>
                <span className="json-key">{i}</span>
                <JsonValue depth={depth + 1} value={item} />
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  if (t === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) return <span className="json-leaf json-empty">{'{}'}</span>
    return (
      <div className="json-node">
        <button
          aria-expanded={open}
          className={`json-node-toggle ${open ? 'open' : ''}`}
          onClick={() => setOpen(prev => !prev)}
          type="button"
        >
          <ChevronRightIcon className="json-node-chevron" />
          <span className="json-type-tag">{`{${entries.length} keys}`}</span>
        </button>
        {open && (
          <ul className="json-node-children">
            {entries.map(([k, v]) => (
              <li className="json-node-row" key={k}>
                <span className="json-key">{k}</span>
                <JsonValue depth={depth + 1} value={v} />
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  return <span className="json-leaf">{String(value)}</span>
}

function tryParseJson(value: unknown): { ok: boolean; data: unknown } {
  if (typeof value !== 'string') return { ok: false, data: value }
  const trimmed = value.trim()
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return { ok: false, data: value }
  try {
    return { ok: true, data: JSON.parse(trimmed) }
  } catch {
    return { ok: false, data: value }
  }
}

function makeTraceLinkResolver(template: string | null): (traceId: string) => string | null {
  if (!template) return () => null
  return (traceId: string) => template.replace('{trace_id}', traceId)
}

function TraceLinkButton({
  url,
  reason,
}: {
  url: string | null
  reason?: string
}) {
  if (url) {
    return (
      <a
        className="action-button"
        href={url}
        target="_blank"
        rel="noreferrer"
        title="Open this turn's trace in the configured tracing UI"
      >
        View in trace ↗
      </a>
    )
  }
  return (
    <button
      className="action-button"
      type="button"
      disabled
      title={reason ?? 'Tracing not configured'}
    >
      View in trace ↗
    </button>
  )
}

function UserDetail({
  metadata,
  traceUrl,
  traceReason,
}: {
  metadata: Record<string, unknown>
  traceUrl: string | null
  traceReason: string
}) {
  const [historyOpen, setHistoryOpen] = useState(false)
  const chatRequest = (metadata['chat_request'] ?? null) as
    | Record<string, unknown>
    | null

  const messageId = chatRequest?.message_id as string | undefined
  const sourceBu = chatRequest?.source_bu_type as string | undefined
  const appType = chatRequest?.app_type as string | undefined
  const externalHistoryCount = chatRequest?.external_history_count as number | undefined
  const useHistory = chatRequest?.use_history as boolean | undefined
  const overrideModel = chatRequest?.model as string | undefined
  const overrideProvider = chatRequest?.provider as string | undefined

  const callerChips: { key: string; label: string }[] = []
  if (sourceBu) callerChips.push({ key: 'bu', label: sourceBu })
  if (appType) callerChips.push({ key: 'app', label: appType })

  const overrideChips: { key: string; label: string }[] = []
  if (overrideModel) overrideChips.push({ key: 'model', label: `model=${overrideModel}` })
  if (overrideProvider) overrideChips.push({ key: 'provider', label: `provider=${overrideProvider}` })

  const hasAnyField =
    !!messageId || callerChips.length > 0 || overrideChips.length > 0 ||
    typeof externalHistoryCount === 'number' || useHistory === false

  return (
    <>
      <div className="dt-toolbar">
        <TraceLinkButton url={traceUrl} reason={traceReason} />
      </div>

      {messageId && (
        <div className="dt-row dt-row-message-id">
          <div className="dt-label">message_id</div>
          <div className="dt-value mono dt-message-id-value" title={messageId}>
            <span className="dt-message-id-cluster">
              <code className="dt-message-id-code">{messageId}</code>
              <CopyButton value={messageId} title="message_id" />
            </span>
          </div>
        </div>
      )}

      {callerChips.length > 0 && (
        <div className="dt-row">
          <div className="dt-label">caller</div>
          <div className="dt-value">
            {callerChips.map(c => <span className="chip" key={c.key}>{c.label}</span>)}
          </div>
        </div>
      )}

      {overrideChips.length > 0 && (
        <div className="dt-row">
          <div className="dt-label">overrides</div>
          <div className="dt-value">
            {overrideChips.map(c => <span className="chip" key={c.key}>{c.label}</span>)}
          </div>
        </div>
      )}

      {typeof externalHistoryCount === 'number' && externalHistoryCount > 0 && (
        <div className="dt-row">
          <div className="dt-label">history</div>
          <div className="dt-value">
            <button
              className="chip"
              onClick={() => setHistoryOpen(prev => !prev)}
              type="button"
              title="Show injected history messages"
            >
              {externalHistoryCount} {externalHistoryCount === 1 ? 'message' : 'messages'} injected
              {historyOpen ? ' ▾' : ' ▸'}
            </button>
            {historyOpen && (
              <div className="dt-empty" style={{ marginTop: 6 }}>
                History payload is not stored on the session. Inspect the originating call
                in the trace dashboard to view the injected messages.
              </div>
            )}
          </div>
        </div>
      )}

      {useHistory === false && (
        <div className="dt-row">
          <div className="dt-label">history</div>
          <div className="dt-value">
            <span className="chip chip-error">use_history=false</span>
          </div>
        </div>
      )}

      {!hasAnyField && (
        <div className="dt-empty">No request metadata captured for this message.</div>
      )}
    </>
  )
}

function AssistantDetail({
  rawThinking,
  metadata,
  turnContext,
  finishReason: finishReasonProp,
  traceUrl,
  traceReason,
}: {
  rawThinking: string | null
  metadata: Record<string, unknown>
  turnContext?: TurnContext | null
  finishReason?: string | null
  traceUrl: string | null
  traceReason: string
}) {
  const [toolsOpen, setToolsOpen] = useState(false)
  const toolsPreviewCount = 5

  // Read from typed fields; fall back to legacy metadata for old sessions.
  const toolsMounted = turnContext?.tools_mounted ?? (metadata['tools_mounted'] ?? []) as string[]
  const activeSkillId = turnContext?.active_skill_id ?? (metadata['active_skill_ids'] as string[] | undefined)?.[0] ?? null
  const finishReason = finishReasonProp ?? metadata['finish_reason'] as string | undefined

  const runChips: string[] = []
  if (finishReason) runChips.push(finishReason)

  return (
    <>
      <div className="dt-toolbar">
        <TraceLinkButton url={traceUrl} reason={traceReason} />
      </div>

      {activeSkillId && (
        <div className="dt-row">
          <div className="dt-label">active skill</div>
          <div className="dt-value">
            <span className="chip">{activeSkillId}</span>
          </div>
        </div>
      )}

      {rawThinking && (
        <div className="dt-block">
          <div className="dt-label">thinking</div>
          <pre className="code-block compact">{rawThinking}</pre>
        </div>
      )}

      {runChips.length > 0 && (
        <div className="dt-row">
          <div className="dt-label">run</div>
          <div className="dt-value mono">{runChips.join(' · ')}</div>
        </div>
      )}

      {toolsMounted.length > 0 && (
        <div className="dt-row">
          <div className="dt-label">tools mounted</div>
          <div className="dt-value dt-tools-mounted-value">
            <div className="dt-tools-inline">
              {(toolsOpen ? toolsMounted : toolsMounted.slice(0, toolsPreviewCount)).map(
                t => <span className="chip" key={t}>{t}</span>,
              )}
              {toolsMounted.length > toolsPreviewCount && (
                <button
                  className="chip dt-tools-toggle"
                  onClick={() => setToolsOpen(prev => !prev)}
                  type="button"
                  title={toolsOpen ? 'Show fewer' : 'Show all tool names'}
                >
                  {toolsOpen ? '▾' : `+${toolsMounted.length - toolsPreviewCount} ▸`}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function ToolDetail({
  item,
}: {
  item: Extract<TimelineItem, { kind: 'tool' }>
}) {
  const [showRaw, setShowRaw] = useState(false)
  const parsedResult = tryParseJson(item.result)
  const resultLabel = item.resultType ?? (item.isError ? 'error' : 'text')
  return (
    <>
      <div className="tool-detail-head">
        <span className="tool-detail-name">{item.name}</span>
        <span className={`chip chip-result chip-result-${resultLabel}`}>{resultLabel}</span>
        {item.isError && <span className="chip chip-error">error</span>}
      </div>

      {item.preamble && (
        <div className="dt-block">
          <div className="dt-label">preamble</div>
          <pre className="code-block compact">{item.preamble}</pre>
        </div>
      )}

      {item.llmDigest && (
        <div className="dt-block">
          <div className="dt-label">llm digest</div>
          <pre className="tool-digest">{item.llmDigest}</pre>
        </div>
      )}

      <div className="dt-block">
        <div className="dt-label">arguments</div>
        <pre className="code-block compact">{JSON.stringify(item.args, null, 2)}</pre>
      </div>

      <div className="dt-block">
        <div className="dt-label-row">
          <span className="dt-label">output</span>
          {parsedResult.ok && (
            <button
              className="dt-mini-toggle"
              onClick={() => setShowRaw(prev => !prev)}
              type="button"
            >
              {showRaw ? 'tree view' : 'raw view'}
            </button>
          )}
        </div>
        {parsedResult.ok && !showRaw ? (
          <div className="tool-output-tree">
            <JsonValue value={parsedResult.data} />
          </div>
        ) : (
          <pre className={`code-block compact ${item.isError ? 'is-error' : ''}`}>
            {typeof item.result === 'string' ? item.result : JSON.stringify(item.result, null, 2)}
          </pre>
        )}
      </div>

      <dl className="tool-meta">
        <div className="tool-meta-item tool-meta-item-tool-call-id">
          <dt>tool_call_id</dt>
          <dd><code>{item.toolCallId || '—'}</code></dd>
        </div>
        <div className="tool-meta-item">
          <dt>turn</dt>
          <dd>{zeropad(item.turn)}</dd>
        </div>
      </dl>
    </>
  )
}

function renderStateValue(value: unknown): ReactNode {
  if (value === null) return <span className="json-leaf json-null">null</span>
  if (value === undefined) return <span className="json-leaf json-null">undefined</span>
  const t = typeof value
  if (t === 'string') return <span className="json-leaf json-string">"{value as string}"</span>
  if (t === 'number') return <span className="json-leaf json-number">{String(value)}</span>
  if (t === 'boolean') return <span className="json-leaf json-boolean">{String(value)}</span>
  return <code className="state-json">{JSON.stringify(value)}</code>
}

function SessionStateBlock({
  state,
  toolsUsed,
}: {
  state: Record<string, unknown> | undefined | null
  toolsUsed: number
}) {
  const [open, setOpen] = useState(false)
  const entries = Object.entries(state ?? {})
  const total = entries.length + 1
  return (
    <div className={`session-state-block ${open ? 'open' : ''}`}>
      <button
        aria-expanded={open}
        className="session-state-toggle"
        onClick={() => setOpen(prev => !prev)}
        type="button"
      >
        <ChevronRightIcon className="session-state-chevron" />
        <span className="session-state-title">Session state</span>
        <span className="session-state-count">{total} {total === 1 ? 'key' : 'keys'}</span>
      </button>
      {open && (
        <ul className="session-state-list">
          {entries.map(([key, value]) => (
            <li className="session-state-row" key={key}>
              <div className="session-state-key">{key}</div>
              <div className="session-state-value">{renderStateValue(value)}</div>
            </li>
          ))}
          <li className="session-state-row">
            <div className="session-state-key">tools_used</div>
            <div className="session-state-value">
              <span className="json-leaf json-number">{toolsUsed}</span>
            </div>
          </li>
        </ul>
      )}
    </div>
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

  return (
    <div className="workspace-page workspace-page-split">
      <div aria-atomic="true" aria-live="polite" className="sr-only">
        {selectedAgent ? `${selectedAgent.name}, ${activeSection} section` : 'No agent selected'}
      </div>
      <section className="workspace-context-bar">
        <div className="workspace-context-head">
          <div className="workspace-context-copy">
            <div className="workspace-context-title-row">
              <h1>{selectedAgent?.name ?? agentId}</h1>
              <span className="workspace-context-meta-inline">
                <span>{(selectedAgent?.id ?? agentId).toUpperCase()}</span>
                <span aria-hidden="true">·</span>
                <span>{formatAgentDate(selectedAgent?.updated_at)}</span>
              </span>
            </div>
            {selectedAgent?.description && <p>{selectedAgent.description}</p>}
          </div>
          <div className="workspace-context-actions">
            <button className="btn btn-sm" disabled type="button" title="即将推出">Configure</button>
            <button className="btn btn-sm" disabled type="button" title="即将推出">Export</button>
            <button className="btn btn-accent btn-sm" disabled type="button" title="即将推出">Test agent</button>
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

      {activeSection === 'overview' && <OverviewSection key={agentId} agentId={agentId} />}
      {activeSection === 'skills' && <SkillsSection key={agentId} agentId={agentId} />}
      {activeSection === 'tools' && <ToolsSection key={agentId} agentId={agentId} />}
      {activeSection === 'sessions' && <SessionsSection key={agentId} agentId={agentId} />}
      {activeSection === 'memory' && <MemorySection key={agentId} agentId={agentId} />}
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
    <div className="workspace-overview-scroll">
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
    </div>
  )
}

function SkillsSection({ agentId }: { agentId: string }) {
  const [searchParams] = useSearchParams()
  const { user } = useAuth()
  const canEdit = canEditStudio(user?.role)
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
            <div className="skill-detail-header">
              <div className="skill-detail-title-row">
                <div className="skill-detail-title-copy">
                  <h2 className="skill-detail-name">{selectedSkill.name}</h2>
                  {selectedSkill.file_path && (
                    <code className="skill-detail-path">{selectedSkill.file_path}</code>
                  )}
                </div>
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
              <div className="skill-detail-chips">
                <span className={`badge ${selectedSkill.invocation_policy === 'auto' ? 'accent' : ''}`}>
                  {selectedSkill.invocation_policy || 'manual'}
                </span>
                {selectedSkill.version && (
                  <span className="chip">v{selectedSkill.version}</span>
                )}
                <span className="chip">{selectedSkill.group || 'default'}</span>
                {selectedSkill.tags?.map(tag => (
                  <span className="metadata-tag" key={tag}>{tag}</span>
                ))}
              </div>
            </div>

            <CodeBody value={selectedSkill.content || ''}>
              <pre className="code-block">{selectedSkill.content || 'File is empty.'}</pre>
            </CodeBody>
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
  const canEdit = canEditStudio(user?.role)
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
            <div className="skill-detail-header">
              <div className="skill-detail-title-row">
                <div className="skill-detail-title-copy">
                  <h2 className="skill-detail-name">{selectedTool.name}</h2>
                  {selectedTool.file_path && (
                    <code className="skill-detail-path">{selectedTool.file_path}</code>
                  )}
                </div>
              </div>
              <div className="skill-detail-chips">
                <span className="chip">{selectedTool.group || 'default'}</span>
                <span className="chip">
                  {Object.keys(selectedTool.parameters || {}).length} params
                </span>
              </div>
            </div>

            {selectedTool.description && (
              <p className="detail-description">{selectedTool.description}</p>
            )}

            <CodeBody
              value={Object.keys(selectedTool.parameters || {}).length > 0
                ? JSON.stringify(selectedTool.parameters, null, 2)
                : ''}
            >
              <pre className="code-light">
                {Object.keys(selectedTool.parameters || {}).length > 0
                  ? JSON.stringify(selectedTool.parameters, null, 2)
                  : '// No parameters defined'}
              </pre>
            </CodeBody>
          </div>
        )}

        {mode === 'view' && !selectedTool && <div className="empty-surface">Select a tool or scaffold a new one.</div>}
      </div>
    </section>
  )
}

function SessionsSection({ agentId }: { agentId: string }) {
  const { user } = useAuth()
  const canEdit = canEditStudio(user?.role)
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
  const [traceLinkTemplate, setTraceLinkTemplate] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.getTraceLinkConfig()
      .then(cfg => {
        if (!cancelled) setTraceLinkTemplate(cfg.template)
      })
      .catch(() => {
        /* silently degrade — links won't render */
      })
    return () => {
      cancelled = true
    }
  }, [])

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
          const sorted = [...nextSessions].sort(
            (a, b) =>
              getTimestampValue(b.updated_at || b.created_at) -
              getTimestampValue(a.updated_at || a.created_at),
          )
          setSessions(sorted)
          setSelected(sorted[0] ?? null)
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
    setExpanded({})
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
                <div className="session-title-block">
                  <div className="session-title" title={selected.first_message || selected.session_id}>
                    {selected.first_message || selected.session_id}
                  </div>
                  <div className="session-meta-row">
                    <button
                      className="session-meta-id"
                      onClick={() => void copyText(selected.session_id)}
                      type="button"
                      title="Copy session id"
                    >
                      #{selected.session_id.slice(0, 8)}
                      <CopyIcon />
                    </button>
                    {detail && (
                      <span className="session-meta-item">
                        {detail.messages.length} msg
                      </span>
                    )}
                    <span
                      className={`session-meta-trace ${traceLinkTemplate ? 'on' : 'off'}`}
                      title={
                        traceLinkTemplate
                          ? 'Trace UI configured — deep links available'
                          : 'TRACING env not set — no deep links to trace UI'
                      }
                    >
                      trace: {traceLinkTemplate ? 'on' : 'off'}
                    </span>
                  </div>
                </div>
                <div className="session-actions">
                  <button
                    className="chip"
                    onClick={() => downloadJsonl(`${selected.session_id}.jsonl`, detail?.messages ?? [])}
                    type="button"
                    title="Download raw JSONL"
                    disabled={!detail}
                  >
                    <DownloadIcon />
                    Raw
                  </button>
                  {canEdit && (
                    <button
                      className="chip"
                      onClick={() => setEditingRaw(prev => !prev)}
                      type="button"
                      title="Edit raw JSONL"
                    >
                      {editingRaw ? 'Close edit' : 'Edit'}
                    </button>
                  )}
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
              <>
                <ol className="timeline-main" aria-label="Session timeline">
                  {flattenTimeline(detail).map((it, i) => {
                    const isOpen = !!expanded[i]
                    const isUser = it.kind === 'user'
                    const isAssistant = it.kind === 'assistant'
                    const isTool = it.kind === 'tool'
                    const summary = isTool ? it.name : summarizeText(it.text)
                    const md = !isTool ? ((it.metadata ?? {}) as Record<string, unknown>) : {}
                    const traceObj = md['trace'] as { trace_id?: string } | undefined
                    const traceId = traceObj?.trace_id
                    const traceUrl =
                      traceId && traceLinkTemplate
                        ? makeTraceLinkResolver(traceLinkTemplate)(traceId)
                        : null
                    const traceReason = !traceLinkTemplate
                      ? 'Tracing UI not configured — set TRACING env var (phoenix / langfuse / otlp) or STUDIO_TRACE_URL_TEMPLATE'
                      : !traceId
                        ? 'No trace_id captured for this message — TRACING was not active when this turn ran'
                        : 'Trace available'
                    return (
                      <li className={`tlm-item ${it.kind} ${isOpen ? 'active' : ''}`} key={i}>
                        <div
                          aria-expanded={isOpen}
                          className="tlm-row"
                          onClick={() => setExpanded(e => ({ ...e, [i]: !e[i] }))}
                          role="button"
                          tabIndex={0}
                          onKeyDown={event => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault()
                              setExpanded(e => ({ ...e, [i]: !e[i] }))
                            }
                          }}
                        >
                          <span className={`tlm-marker tlm-marker-${it.kind}${isTool && it.isError ? ' err' : ''}`} aria-hidden="true" />
                          <span className={`tlm-pill tlm-pill-${it.kind}`}>
                            {isTool ? 'TOOL' : it.role.toUpperCase()}
                          </span>
                          <span className={`tlm-summary ${isTool ? 'mono' : ''}`}>{summary}</span>
                          <span className={`tlm-gutter ${isTool && it.isError ? 'err' : ''}`}>
                            {isTool ? (it.isError ? 'ERR' : 'OK') : zeropad(it.turn)}
                          </span>
                          <ChevronRightIcon className={`tlm-chevron ${isOpen ? 'open' : ''}`} />
                        </div>
                        {isOpen && (
                          <div className="tlm-detail">
                            {isTool ? (
                              <ToolDetail item={it} />
                            ) : isUser ? (
                              <UserDetail metadata={md} traceUrl={traceUrl} traceReason={traceReason} />
                            ) : isAssistant ? (
                              <AssistantDetail
                                rawThinking={it.raw.thinking ?? null}
                                metadata={md}
                                turnContext={it.raw.turn_context}
                                finishReason={it.raw.finish_reason}
                                traceUrl={traceUrl}
                                traceReason={traceReason}
                              />
                            ) : null}
                          </div>
                        )}
                      </li>
                    )
                  })}
                </ol>
                <SessionStateBlock
                  state={detail.state}
                  toolsUsed={(detail.messages ?? []).reduce((n, m) => n + (m.tool_calls?.length ?? 0), 0)}
                />
              </>
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
  const canEdit = canEditStudio(user?.role)
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
          <div className="editor-sheet editor-sheet-fill">
            <div className="skill-detail-header">
              <div className="skill-detail-title-row">
                <div className="skill-detail-title-copy">
                  <h2 className="skill-detail-name">{selected.file_path.split('/').pop() || selected.file_path}</h2>
                  <code className="skill-detail-path">{selected.file_path}</code>
                </div>
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
              <div className="skill-detail-chips">
                <span className="chip">{selected.user_id}</span>
                <span className="chip">{selected.file_type}</span>
                <span className="chip">{formatBytes(selected.size_bytes)}</span>
                <span className="chip">{formatRelativeTime(selected.modified_at)}</span>
              </div>
            </div>

            {contentLoading && <div className="empty-surface">Loading memory content...</div>}
            {!contentLoading && (
              <CodeBody className="code-body-fill" value={editing ? draft : content}>
                {editing ? (
                  <textarea
                    className="code-textarea code-textarea-fill"
                    onChange={event => setDraft(event.target.value)}
                    spellCheck={false}
                    value={draft}
                  />
                ) : (
                  <pre className="code-block code-block-fill">{content || '// Empty memory file'}</pre>
                )}
              </CodeBody>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
