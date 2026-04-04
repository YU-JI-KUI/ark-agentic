import { useEffect, useState, useCallback } from 'react'
import { api, type ToolMeta } from '../api'
import { useAuth } from '../auth'

interface Props { agentId: string }

type Mode = 'view' | 'scaffold'

export default function ToolsView({ agentId }: Props) {
    const { user } = useAuth()
    const isEditor = user?.role === 'editor'
    const [tools, setTools] = useState<ToolMeta[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selected, setSelected] = useState<ToolMeta | null>(null)
    const [mode, setMode] = useState<Mode>('view')
    const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)

    // Form state
    const [formName, setFormName] = useState('')
    const [formDesc, setFormDesc] = useState('')

    const showToast = useCallback((msg: string, type: 'success' | 'error' = 'success') => {
        setToast({ msg, type })
        setTimeout(() => setToast(null), 3000)
    }, [])

    const reload = useCallback(() => {
        setLoading(true)
        api.listTools(agentId)
            .then(data => { setTools(data); if (!selected) setSelected(data[0] || null) })
            .catch(e => setError(e.message))
            .finally(() => setLoading(false))
    }, [agentId, selected])

    useEffect(() => { reload() }, [agentId])

    const enterScaffold = () => {
        setMode('scaffold'); setFormName(''); setFormDesc('')
        setSelected(null)
    }

    const cancelForm = () => { setMode('view') }

    const handleScaffold = async () => {
        try {
            const meta = await api.scaffoldTool(agentId, {
                name: formName, description: formDesc,
            })
            showToast(`Tool "${meta.name}" scaffolded`)
            setMode('view')
            reload()
            setSelected(meta)
        } catch (e: any) { showToast(e.message, 'error') }
    }

    if (loading) return <div className="loading"><div className="spinner" /></div>
    if (error) return <div className="empty-state"><h3>⚠️ {error}</h3></div>

    return (
        <div className="master-detail-container">
            {/* Left: Tools Menu */}
            <div className="layout-pane-left">
                <div className="list-header">Tools ({tools.length})</div>
                {isEditor && <button className="btn-create" onClick={enterScaffold}>＋ New Tool</button>}

                <div className="list-scroll">
                    {tools.length === 0 && mode !== 'scaffold' ? (
                        <div className="empty-state" style={{ padding: 'var(--space-xl) var(--space-md)' }}>
                            <div className="empty-state-icon" style={{ fontSize: 32 }}>🔧</div>
                            <p style={{ fontSize: 13 }}>No tools yet.</p>
                        </div>
                    ) : (
                        tools.map(tool => (
                            <div
                                key={tool.name}
                                className={`list-item ${selected?.name === tool.name && mode === 'view' ? 'active' : ''}`}
                                onClick={() => { setSelected(tool); setMode('view') }}
                            >
                                <div className="list-item-title" style={{ fontFamily: 'monospace' }}>{tool.name}</div>
                                <div className="list-item-desc">{tool.description || tool.file_path}</div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Right: Detail / Scaffold Form */}
            <div className="layout-pane-main">
                {mode === 'scaffold' ? (
                    <>
                        <div className="detail-header">
                            <div className="detail-header-inner">
                                <span className="detail-icon">✨</span>
                                <div>
                                    <div className="detail-title">Scaffold New Tool</div>
                                    <div className="detail-subtitle">Generate an AgentTool Python template</div>
                                </div>
                            </div>
                        </div>
                        <div className="detail-body">
                            <div className="form-group">
                                <label className="form-label">Name (Python identifier)</label>
                                <input className="form-input" value={formName}
                                    onChange={e => setFormName(e.target.value)}
                                    placeholder="e.g. customer_lookup" style={{ fontFamily: 'monospace' }} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Description</label>
                                <input className="form-input" value={formDesc}
                                    onChange={e => setFormDesc(e.target.value)}
                                    placeholder="What does this tool do?" />
                            </div>
                            <div style={{ display: 'flex', gap: 8 }}>
                                <button className="btn-save"
                                    onClick={handleScaffold}
                                    disabled={!formName.trim()}>
                                    ✓ Generate
                                </button>
                                <button className="btn-action" onClick={cancelForm}>Cancel</button>
                            </div>
                        </div>
                    </>
                ) : selected ? (
                    <>
                        <div className="detail-header">
                            <div className="detail-header-inner">
                                <span className="detail-icon">🔧</span>
                                <div>
                                    <div className="detail-title" style={{ fontFamily: 'monospace' }}>{selected.name}</div>
                                    <div className="detail-subtitle">{selected.description || 'No description provided'}</div>
                                </div>
                            </div>
                        </div>

                        <div className="detail-body">
                            <div className="metadata-card">
                                <div className="metadata-label">Group</div>
                                <div className="metadata-value">
                                    <span style={{
                                        padding: '2px 8px', borderRadius: 12,
                                        background: 'var(--color-primary-light)', color: 'var(--color-primary)',
                                        fontSize: 12, fontWeight: 500
                                    }}>{selected.group || 'default'}</span>
                                </div>
                                <div className="metadata-label">Source File</div>
                                <div className="metadata-value">{selected.file_path}</div>
                            </div>

                            <h3 className="section-heading">Tool Parameters Schema</h3>
                            <div className="code-block">
                                {Object.keys(selected.parameters || {}).length > 0
                                    ? JSON.stringify(selected.parameters, null, 2)
                                    : '// No parameters defined for this tool'}
                            </div>
                        </div>
                    </>
                ) : (
                    <div className="empty-state">
                        <div className="empty-state-icon">👈</div>
                        <h3>Select a tool or scaffold a new one</h3>
                    </div>
                )}
            </div>

            {/* Toast */}
            {toast && <div className={`toast toast-${toast.type}`}>{toast.msg}</div>}
        </div>
    )
}
