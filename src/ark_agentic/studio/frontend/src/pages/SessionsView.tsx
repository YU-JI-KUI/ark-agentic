import { useCallback, useEffect, useState } from 'react'
import { api, type MessageItem, type SessionItem, type SessionDetail } from '../api'

interface Props { agentId: string }

type ViewTab = 'conversation' | 'raw'

function MessageBlock({ msg }: { msg: MessageItem }) {
    const [expandTool, setExpandTool] = useState(false)
    const [expandThinking, setExpandThinking] = useState(false)
    const [expandMeta, setExpandMeta] = useState(false)
    const roleLabel = msg.role === 'user' ? 'User' : msg.role === 'assistant' ? 'Assistant' : msg.role
    const hasExtra = !!(msg.tool_calls?.length || msg.tool_results?.length || msg.thinking || (msg.metadata && Object.keys(msg.metadata).length > 0))

    return (
        <div className="detail-body" style={{ marginBottom: 'var(--space-lg)', borderLeft: '3px solid var(--color-border)', paddingLeft: 'var(--space-md)' }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: 4 }}>{roleLabel}</div>
            {msg.content != null && msg.content !== '' && (
                <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{msg.content}</div>
            )}
            {msg.tool_calls && msg.tool_calls.length > 0 && (
                <div style={{ marginTop: 8 }}>
                    <button type="button" className="btn-action" style={{ fontSize: 12 }} onClick={() => setExpandTool(!expandTool)}>
                        {expandTool ? 'Hide' : 'Show'} tool_calls ({msg.tool_calls.length})
                    </button>
                    {expandTool && (
                        <pre className="code-block" style={{ marginTop: 4, fontSize: 12 }}>{JSON.stringify(msg.tool_calls, null, 2)}</pre>
                    )}
                </div>
            )}
            {msg.tool_results && msg.tool_results.length > 0 && (
                <div style={{ marginTop: 8 }}>
                    {expandTool && (
                        <pre className="code-block" style={{ fontSize: 12 }}>{JSON.stringify(msg.tool_results, null, 2)}</pre>
                    )}
                </div>
            )}
            {msg.thinking && (
                <div style={{ marginTop: 8 }}>
                    <button type="button" className="btn-action" style={{ fontSize: 12 }} onClick={() => setExpandThinking(!expandThinking)}>
                        {expandThinking ? 'Hide' : 'Show'} thinking
                    </button>
                    {expandThinking && (
                        <pre className="code-block" style={{ marginTop: 4, fontSize: 12, background: 'var(--color-bg-secondary)' }}>{msg.thinking}</pre>
                    )}
                </div>
            )}
            {msg.metadata && Object.keys(msg.metadata).length > 0 && (
                <div style={{ marginTop: 8 }}>
                    <button type="button" className="btn-action" style={{ fontSize: 12 }} onClick={() => setExpandMeta(!expandMeta)}>
                        {expandMeta ? 'Hide' : 'Show'} metadata
                    </button>
                    {expandMeta && (
                        <pre className="code-block" style={{ marginTop: 4, fontSize: 12 }}>{JSON.stringify(msg.metadata, null, 2)}</pre>
                    )}
                </div>
            )}
            {!msg.content && !hasExtra && <span style={{ color: 'var(--color-text-secondary)', fontSize: 12 }}>—</span>}
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

    useEffect(() => {
        setLoading(true)
        setError(null)
        api.listSessions(agentId)
            .then(data => { setSessions(data); setSelected(data[0] || null) })
            .catch(e => setError(e.message))
            .finally(() => setLoading(false))
    }, [agentId])

    const loadDetail = useCallback(async (sid: string) => {
        setDetailLoading(true)
        setDetail(null)
        try {
            const d = await api.getSessionDetail(agentId, sid)
            setDetail(d)
        } catch {
            setDetail(null)
        } finally {
            setDetailLoading(false)
        }
    }, [agentId])

    const loadRaw = useCallback(async (sid: string) => {
        setRawLoading(true)
        setRaw(null)
        setRawEdit(false)
        try {
            const text = await api.getSessionRaw(agentId, sid)
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
        if (tab === 'conversation') loadDetail(selected.session_id)
        else loadRaw(selected.session_id)
    }, [selected?.session_id, tab, loadDetail, loadRaw])

    const handleSaveRaw = async () => {
        if (!selected) return
        setSaveStatus('saving')
        try {
            await api.putSessionRaw(agentId, selected.session_id, rawDraft)
            setRaw(rawDraft)
            setRawEdit(false)
            setSaveStatus('ok')
            setTimeout(() => setSaveStatus('idle'), 2000)
        } catch {
            setSaveStatus('err')
            setTimeout(() => setSaveStatus('idle'), 3000)
        }
    }

    if (loading) return <div className="loading"><div className="spinner" /></div>
    if (error) return <div className="empty-state"><h3>⚠️ {error}</h3></div>

    return (
        <div className="master-detail-container">
            <div className="layout-pane-left">
                <div className="list-header">Sessions ({sessions.length})</div>
                <div className="list-scroll">
                    {sessions.length === 0 ? (
                        <div className="empty-state" style={{ padding: 'var(--space-xl) var(--space-md)' }}>
                            <div className="empty-state-icon" style={{ fontSize: 32 }}>💬</div>
                            <p style={{ fontSize: 13 }}>No sessions yet.</p>
                        </div>
                    ) : (
                        sessions.map(s => (
                            <div
                                key={s.session_id}
                                className={`list-item ${selected?.session_id === s.session_id ? 'active' : ''}`}
                                onClick={() => setSelected(s)}
                            >
                                <div className="list-item-title" style={{ fontFamily: 'monospace' }}>{s.session_id.substring(0, 16)}...</div>
                                <div className="list-item-desc">Messages: {s.message_count}</div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            <div className="layout-pane-main">
                {selected ? (
                    <>
                        <div className="detail-header">
                            <div className="detail-header-inner">
                                <span className="detail-icon">💬</span>
                                <div>
                                    <div className="detail-title" style={{ fontFamily: 'monospace' }}>{selected.session_id}</div>
                                    <div className="detail-subtitle">Session — view &amp; edit</div>
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                                <button
                                    type="button"
                                    className={`btn-action ${tab === 'conversation' ? 'active' : ''}`}
                                    onClick={() => setTab('conversation')}
                                >
                                    Conversation
                                </button>
                                <button
                                    type="button"
                                    className={`btn-action ${tab === 'raw' ? 'active' : ''}`}
                                    onClick={() => setTab('raw')}
                                >
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
                                            <div className="metadata-card" style={{ marginBottom: 'var(--space-lg)' }}>
                                                <div className="metadata-label">Message Count</div>
                                                <div className="metadata-value">{detail.message_count}</div>
                                                <div className="metadata-label">State</div>
                                                <div className="metadata-value">
                                                    {Object.keys(detail.state || {}).length > 0 ? JSON.stringify(detail.state) : '—'}
                                                </div>
                                            </div>
                                            <h3 className="section-heading">Messages</h3>
                                            {detail.messages.length === 0 ? (
                                                <p style={{ color: 'var(--color-text-secondary)' }}>No messages.</p>
                                            ) : (
                                                detail.messages.map((msg, i) => <MessageBlock key={i} msg={msg} />)
                                            )}
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
                                                    {saveStatus === 'saving' ? 'Saving…' : 'Save'}
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
                        <div className="empty-state-icon">👈</div>
                        <h3>Select a session</h3>
                    </div>
                )}
            </div>
        </div>
    )
}
