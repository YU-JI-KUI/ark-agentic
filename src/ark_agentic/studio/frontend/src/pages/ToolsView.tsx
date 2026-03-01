import { useEffect, useState } from 'react'
import { api, type ToolMeta } from '../api'

interface Props { agentId: string }

export default function ToolsView({ agentId }: Props) {
    const [tools, setTools] = useState<ToolMeta[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selected, setSelected] = useState<ToolMeta | null>(null)

    useEffect(() => {
        setLoading(true)
        setError(null)
        api.listTools(agentId)
            .then(data => { setTools(data); setSelected(data[0] || null) })
            .catch(e => setError(e.message))
            .finally(() => setLoading(false))
    }, [agentId])

    if (loading) return <div className="loading"><div className="spinner" /></div>
    if (error) return <div className="empty-state"><h3>⚠️ {error}</h3></div>

    return (
        <div className="master-detail-container">
            {/* Left: Tools Menu */}
            <div className="layout-pane-left">
                <div className="list-header">Bound Tools ({tools.length})</div>

                <div className="list-scroll">
                    {tools.length === 0 ? (
                        <div className="empty-state" style={{ padding: 'var(--space-xl) var(--space-md)' }}>
                            <div className="empty-state-icon" style={{ fontSize: 32 }}>🔧</div>
                            <p style={{ fontSize: 13 }}>No tools yet.</p>
                        </div>
                    ) : (
                        tools.map(tool => (
                            <div
                                key={tool.name}
                                className={`list-item ${selected?.name === tool.name ? 'active' : ''}`}
                                onClick={() => setSelected(tool)}
                            >
                                <div className="list-item-title" style={{ fontFamily: 'monospace' }}>{tool.name}</div>
                                <div className="list-item-desc">{tool.description || tool.file_path}</div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Right: Tool Detail Area */}
            <div className="layout-pane-main">
                {selected ? (
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
                        <h3>Select a tool to view its properties</h3>
                    </div>
                )}
            </div>
        </div>
    )
}
