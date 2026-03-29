import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type SessionItem, type SessionDetail } from '../api'
import MessageBlock from '../components/MessageBlock'

interface Props { agentId: string }

type ViewTab = 'conversation' | 'raw'

function relativeTime(iso: string | null): string {
    if (!iso) return ''
    const diff = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    const days = Math.floor(hrs / 24)
    return `${days}d ago`
}

function StateViewer({ state }: { state: Record<string, unknown> }) {
    const [expanded, setExpanded] = useState<Record<string, boolean>>({})
    const keys = Object.keys(state || {})
    if (keys.length === 0) return <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 'var(--space-md)' }}>{'\u2014'}</div>

    const toggle = (k: string) => setExpanded(prev => ({ ...prev, [k]: !prev[k] }))
    const preview = (v: unknown) => {
        const s = typeof v === 'string' ? v : JSON.stringify(v)
        return s.length > 60 ? s.slice(0, 60) + '\u2026' : s
    }

    return (
        <div className="state-viewer">
            <div className="state-viewer-title">State ({keys.length} keys)</div>
            {keys.map(k => {
                const isTemp = k.startsWith('temp:')
                return (
                    <div key={k} className={`state-viewer-row ${isTemp ? 'state-viewer-temp' : ''}`}>
                        <button type="button" className="state-viewer-key" onClick={() => toggle(k)}>
                            <span>{expanded[k] ? '\u25BC' : '\u25B6'}</span>
                            <span className="state-viewer-key-name">{k}</span>
                            {!expanded[k] && <span className="state-viewer-preview">{preview(state[k])}</span>}
                        </button>
                        {expanded[k] && (
                            <pre className="state-viewer-value">{JSON.stringify(state[k], null, 2)}</pre>
                        )}
                    </div>
                )
            })}
        </div>
    )
}

export default function SessionsView({ agentId }: Props) {
    const [sessions, setSessions] = useState<SessionItem[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selected, setSelected] = useState<SessionItem | null>(null)
    const [tab, setTab] = useState<ViewTab>('conversation')
    const [detail, setDetail] = useState<SessionDetail | null>(null)
    const [detailLoading, setDetailLoading] = useState(false)
    const [raw, setRaw] = useState<string | null>(null)
    const [rawLoading, setRawLoading] = useState(false)
    const [rawEdit, setRawEdit] = useState(false)
    const [rawDraft, setRawDraft] = useState('')
    const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'ok' | 'err'>('idle')
    const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

    const grouped = useMemo(() => {
        const map = new Map<string, SessionItem[]>()
        for (const s of sessions) {
            const key = s.user_id || '(anonymous)'
            const arr = map.get(key) || []
            arr.push(s)
            map.set(key, arr)
        }
        const sessionTime = (s: SessionItem) =>
            s.updated_at ? new Date(s.updated_at).getTime()
            : s.created_at ? new Date(s.created_at).getTime() : 0
        for (const arr of map.values()) {
            arr.sort((a, b) => sessionTime(b) - sessionTime(a))
        }
        const entries = [...map.entries()].sort((a, b) => {
            const aMax = Math.max(...a[1].map(sessionTime))
            const bMax = Math.max(...b[1].map(sessionTime))
            return bMax - aMax
        })
        if (entries.length > 0) {
            const init: Record<string, boolean> = {}
            for (let i = 0; i < entries.length; i++) init[entries[i][0]] = i !== 0
            setCollapsed(prev => Object.keys(prev).length === 0 ? init : prev)
        }
        return entries
    }, [sessions])

    useEffect(() => {
        setLoading(true)
        setError(null)
        api.listSessions(agentId)
            .then(data => { setSessions(data); setSelected(data[0] || null) })
            .catch(e => setError(e.message))
            .finally(() => setLoading(false))
    }, [agentId])

    const loadDetail = useCallback(async (s: SessionItem) => {
        setDetailLoading(true)
        setDetail(null)
        try {
            const d = await api.getSessionDetail(agentId, s.session_id, s.user_id)
            setDetail(d)
        } catch {
            setDetail(null)
        } finally {
            setDetailLoading(false)
        }
    }, [agentId])

    const loadRaw = useCallback(async (s: SessionItem) => {
        setRawLoading(true)
        setRaw(null)
        setRawEdit(false)
        try {
            const text = await api.getSessionRaw(agentId, s.session_id, s.user_id)
            setRaw(text)
            setRawDraft(text)
        } catch {
            setRaw(null)
        } finally {
            setRawLoading(false)
        }
    }, [agentId])

    useEffect(() => {
        if (!selected) return
        if (tab === 'conversation') loadDetail(selected)
        else loadRaw(selected)
    }, [selected?.session_id, tab, loadDetail, loadRaw])

    const handleSaveRaw = async () => {
        if (!selected) return
        setSaveStatus('saving')
        try {
            await api.putSessionRaw(agentId, selected.session_id, selected.user_id, rawDraft)
            setRaw(rawDraft)
            setRawEdit(false)
            setSaveStatus('ok')
            setTimeout(() => setSaveStatus('idle'), 2000)
        } catch {
            setSaveStatus('err')
            setTimeout(() => setSaveStatus('idle'), 3000)
        }
    }

    const toggleGroup = (uid: string) => setCollapsed(prev => ({ ...prev, [uid]: !prev[uid] }))

    if (loading) return <div className="loading"><div className="spinner" /></div>
    if (error) return <div className="empty-state"><h3>{error}</h3></div>

    let turnCounter = 0

    return (
        <div className="master-detail-container">
            {/* ── Left: session list grouped by user ── */}
            <div className="layout-pane-left">
                <div className="list-header">Sessions ({sessions.length})</div>
                <div className="list-scroll">
                    {sessions.length === 0 ? (
                        <div className="empty-state" style={{ padding: 'var(--space-xl) var(--space-md)' }}>
                            <p style={{ fontSize: 13 }}>No sessions yet.</p>
                        </div>
                    ) : (
                        grouped.map(([uid, items]) => (
                            <div key={uid}>
                                <button
                                    type="button"
                                    className="session-group-header"
                                    onClick={() => toggleGroup(uid)}
                                >
                                    <span>{collapsed[uid] ? '\u25B6' : '\u25BC'}</span>
                                    <span style={{ flex: 1 }}>{uid}</span>
                                    <span className="session-group-count">{items.length}</span>
                                </button>
                                {!collapsed[uid] && items.map(s => (
                                    <div
                                        key={s.session_id}
                                        className={`list-item ${selected?.session_id === s.session_id ? 'active' : ''}`}
                                        onClick={() => setSelected(s)}
                                    >
                                        <div className="list-item-title">
                                            {s.first_message || s.session_id.substring(0, 12) + '...'}
                                        </div>
                                        <div className="list-item-desc">
                                            {relativeTime(s.updated_at || s.created_at)} &middot; {s.message_count} msgs
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* ── Right: detail ── */}
            <div className="layout-pane-main">
                {selected ? (
                    <>
                        <div className="detail-header">
                            <div className="detail-header-inner">
                                <span className="detail-icon">{'\uD83D\uDCAC'}</span>
                                <div>
                                    <div className="detail-title" style={{ fontFamily: 'monospace', fontSize: 16 }}>{selected.session_id}</div>
                                    <div className="detail-subtitle">{selected.user_id} &middot; {relativeTime(selected.created_at)}</div>
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                                <button type="button" className={`btn-action ${tab === 'conversation' ? 'active' : ''}`} onClick={() => setTab('conversation')}>
                                    Conversation
                                </button>
                                <button type="button" className={`btn-action ${tab === 'raw' ? 'active' : ''}`} onClick={() => setTab('raw')}>
                                    Raw JSONL
                                </button>
                            </div>
                        </div>

                        <div className="detail-body">
                            {tab === 'conversation' && (
                                <>
                                    {detailLoading && <div className="loading"><div className="spinner" /></div>}
                                    {!detailLoading && detail && (
                                        <>
                                            <div className="metadata-card" style={{ marginBottom: 'var(--space-md)' }}>
                                                <div className="metadata-label">Messages</div>
                                                <div className="metadata-value">{detail.message_count}</div>
                                            </div>
                                            <StateViewer state={detail.state} />
                                            {detail.messages.map((msg, i) => {
                                                const showTurnDivider = msg.role === 'user' && turnCounter > 0
                                                if (msg.role === 'user') turnCounter++
                                                return (
                                                    <div key={i}>
                                                        {showTurnDivider && (
                                                            <div className="turn-divider"><span className="turn-label">Turn {turnCounter}</span></div>
                                                        )}
                                                        <MessageBlock msg={msg} index={i} messages={detail.messages} />
                                                    </div>
                                                )
                                            })}
                                            {(() => { turnCounter = 0; return null })()}
                                        </>
                                    )}
                                    {!detailLoading && !detail && selected && <p style={{ color: 'var(--color-text-secondary)' }}>Failed to load detail.</p>}
                                </>
                            )}

                            {tab === 'raw' && (
                                <>
                                    {rawLoading && <div className="loading"><div className="spinner" /></div>}
                                    {!rawLoading && raw !== null && !rawEdit && (
                                        <>
                                            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
                                                <button type="button" className="btn-action" onClick={() => setRawEdit(true)}>Edit</button>
                                            </div>
                                            <pre className="code-block" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 12 }}>{raw}</pre>
                                        </>
                                    )}
                                    {!rawLoading && raw !== null && rawEdit && (
                                        <>
                                            <textarea
                                                value={rawDraft}
                                                onChange={e => setRawDraft(e.target.value)}
                                                className="code-block"
                                                style={{ width: '100%', minHeight: 320, fontFamily: 'monospace', fontSize: 12, resize: 'vertical' }}
                                                spellCheck={false}
                                            />
                                            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                                                <button type="button" className="btn-action" onClick={handleSaveRaw} disabled={saveStatus === 'saving'}>
                                                    {saveStatus === 'saving' ? 'Saving\u2026' : 'Save'}
                                                </button>
                                                <button type="button" className="btn-action" onClick={() => { setRawEdit(false); setRawDraft(raw); }}>Cancel</button>
                                                {saveStatus === 'ok' && <span style={{ color: 'var(--color-success)' }}>Saved.</span>}
                                                {saveStatus === 'err' && <span style={{ color: 'var(--color-error)' }}>Save failed.</span>}
                                            </div>
                                        </>
                                    )}
                                    {!rawLoading && raw === null && selected && <p style={{ color: 'var(--color-text-secondary)' }}>Failed to load raw.</p>}
                                </>
                            )}
                        </div>
                    </>
                ) : (
                    <div className="empty-state">
                        <h3>Select a session</h3>
                    </div>
                )}
            </div>
        </div>
    )
}
