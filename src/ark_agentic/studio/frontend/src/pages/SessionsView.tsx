import { useEffect, useState } from 'react'
import { api, type SessionItem } from '../api'

interface Props { agentId: string }

export default function SessionsView({ agentId }: Props) {
    const [sessions, setSessions] = useState<SessionItem[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selected, setSelected] = useState<SessionItem | null>(null)

    useEffect(() => {
        setLoading(true)
        setError(null)
        api.listSessions(agentId)
            .then(data => { setSessions(data); setSelected(data[0] || null) })
            .catch(e => setError(e.message))
            .finally(() => setLoading(false))
    }, [agentId])

    if (loading) return <div className="loading"><div className="spinner" /></div>
    if (error) return <div className="empty-state"><h3>⚠️ {error}</h3></div>

    return (
        <div className="master-detail-container">
            {/* Left: Sessions Menu */}
            <div className="layout-pane-left">
                <div className="list-header">Active Sessions ({sessions.length})</div>

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

            {/* Right: Session Detail Area */}
            <div className="layout-pane-main">
                {selected ? (
                    <>
                        <div className="detail-header">
                            <div className="detail-header-inner">
                                <span className="detail-icon">💬</span>
                                <div>
                                    <div className="detail-title" style={{ fontFamily: 'monospace' }}>{selected.session_id}</div>
                                    <div className="detail-subtitle">Session Details &amp; State</div>
                                </div>
                            </div>
                        </div>

                        <div className="detail-body">
                            <div className="metadata-card">
                                <div className="metadata-label">Message Count</div>
                                <div className="metadata-value">{selected.message_count}</div>

                                <div className="metadata-label">Status</div>
                                <div className="metadata-value">
                                    <span style={{
                                        padding: '2px 8px', borderRadius: 12,
                                        background: 'var(--color-primary-light)', color: 'var(--color-primary)',
                                        fontSize: 12, fontWeight: 500
                                    }}>active</span>
                                </div>
                            </div>

                            <h3 className="section-heading">Internal State (Memory)</h3>

                            <div className="code-block">
                                {Object.keys(selected.state || {}).length > 0
                                    ? JSON.stringify(selected.state, null, 2)
                                    : '// No state recorded for this session'}
                            </div>
                        </div>
                    </>
                ) : (
                    <div className="empty-state">
                        <div className="empty-state-icon">👈</div>
                        <h3>Select a session to view state details</h3>
                    </div>
                )}
            </div>
        </div>
    )
}
