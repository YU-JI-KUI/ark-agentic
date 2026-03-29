import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type MemoryFileItem } from '../api'

interface Props { agentId: string }

function formatBytes(b: number): string {
    if (b < 1024) return `${b} B`
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
    return `${(b / (1024 * 1024)).toFixed(1)} MB`
}

function MemoryContent({ content }: { content: string }) {
    const lines = content.split('\n')
    return (
        <div className="memory-content">
            {lines.map((line, i) => {
                if (line.startsWith('## ')) {
                    return <div key={i} className="memory-content-heading">{line.slice(3)}</div>
                }
                if (line.startsWith('# ')) {
                    return <div key={i} className="memory-content-heading" style={{ fontSize: 17 }}>{line.slice(2)}</div>
                }
                return <div key={i}>{line || '\u00A0'}</div>
            })}
        </div>
    )
}

export default function MemoryView({ agentId }: Props) {
    const [files, setFiles] = useState<MemoryFileItem[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selected, setSelected] = useState<MemoryFileItem | null>(null)
    const [content, setContent] = useState<string | null>(null)
    const [contentLoading, setContentLoading] = useState(false)
    const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
    const [editing, setEditing] = useState(false)
    const [draft, setDraft] = useState('')
    const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'ok' | 'err'>('idle')

    const grouped = useMemo(() => {
        const map = new Map<string, MemoryFileItem[]>()
        for (const f of files) {
            const key = f.user_id || '(global)'
            const arr = map.get(key) || []
            arr.push(f)
            map.set(key, arr)
        }
        const globalGroup = map.get('(global)')
        const entries: [string, MemoryFileItem[]][] = []
        if (globalGroup) {
            entries.push(['(global)', globalGroup])
            map.delete('(global)')
        }
        for (const entry of [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
            entries.push(entry)
        }
        return entries
    }, [files])

    useEffect(() => {
        setLoading(true)
        setError(null)
        api.listMemoryFiles(agentId)
            .then(data => { setFiles(data); setSelected(data[0] || null) })
            .catch(e => setError(e.message))
            .finally(() => setLoading(false))
    }, [agentId])

    const loadContent = useCallback(async (f: MemoryFileItem) => {
        setContentLoading(true)
        setContent(null)
        try {
            const text = await api.getMemoryContent(agentId, f.file_path, f.user_id)
            setContent(text)
        } catch {
            setContent(null)
        } finally {
            setContentLoading(false)
        }
    }, [agentId])

    useEffect(() => {
        if (selected) {
            setEditing(false)
            loadContent(selected)
        }
    }, [selected?.file_path, selected?.user_id, loadContent])

    const handleSave = async () => {
        if (!selected) return
        setSaveStatus('saving')
        try {
            await api.putMemoryContent(agentId, selected.file_path, selected.user_id, draft)
            setContent(draft)
            setEditing(false)
            setSaveStatus('ok')
            api.listMemoryFiles(agentId).then(setFiles).catch(() => {})
            setTimeout(() => setSaveStatus('idle'), 2000)
        } catch {
            setSaveStatus('err')
            setTimeout(() => setSaveStatus('idle'), 3000)
        }
    }

    const toggleGroup = (key: string) => setCollapsed(prev => ({ ...prev, [key]: !prev[key] }))

    const typeLabel = (t: string) => {
        if (t === 'profile') return 'Profile'
        if (t === 'agent_memory') return 'Memory'
        if (t === 'knowledge') return 'Knowledge'
        return t
    }

    if (loading) return <div className="loading"><div className="spinner" /></div>
    if (error) return <div className="empty-state"><h3>{error}</h3></div>

    return (
        <div className="master-detail-container">
            <div className="layout-pane-left">
                <div className="list-header">Memory Files ({files.length})</div>
                <div className="list-scroll">
                    {files.length === 0 ? (
                        <div className="empty-state" style={{ padding: 'var(--space-xl) var(--space-md)' }}>
                            <p style={{ fontSize: 13 }}>No memory files found.</p>
                            <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 4 }}>
                                Memory is not enabled or no MEMORY.md files exist yet.
                            </p>
                        </div>
                    ) : (
                        grouped.map(([key, items]) => (
                            <div key={key}>
                                <button
                                    type="button"
                                    className="session-group-header"
                                    onClick={() => toggleGroup(key)}
                                >
                                    <span>{collapsed[key] ? '\u25B6' : '\u25BC'}</span>
                                    <span style={{ flex: 1 }}>{key}</span>
                                    <span className="session-group-count">{items.length}</span>
                                </button>
                                {!collapsed[key] && items.map(f => (
                                    <div
                                        key={`${f.user_id}/${f.file_path}`}
                                        className={`list-item ${selected?.file_path === f.file_path && selected?.user_id === f.user_id ? 'active' : ''}`}
                                        onClick={() => setSelected(f)}
                                    >
                                        <div className="list-item-title">{f.file_path.split('/').pop()}</div>
                                        <div className="list-item-desc">
                                            {typeLabel(f.file_type)} &middot; {formatBytes(f.size_bytes)}
                                        </div>
                                    </div>
                                ))}
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
                                <span className="detail-icon">{'\uD83D\uDCDA'}</span>
                                <div>
                                    <div className="detail-title" style={{ fontSize: 16 }}>{selected.file_path}</div>
                                    <div className="detail-subtitle">
                                        {typeLabel(selected.file_type)}
                                        {selected.user_id && ` \u00B7 ${selected.user_id}`}
                                        {' \u00B7 '}{formatBytes(selected.size_bytes)}
                                        {selected.modified_at && ` \u00B7 ${new Date(selected.modified_at).toLocaleString()}`}
                                    </div>
                                </div>
                            </div>
                            {!contentLoading && content !== null && !editing && (
                                <button type="button" className="btn-action" onClick={() => { setDraft(content); setEditing(true) }}>Edit</button>
                            )}
                        </div>
                        <div className="detail-body">
                            {contentLoading && <div className="loading"><div className="spinner" /></div>}
                            {!contentLoading && content !== null && !editing && <MemoryContent content={content} />}
                            {!contentLoading && content !== null && editing && (
                                <>
                                    <textarea
                                        value={draft}
                                        onChange={e => setDraft(e.target.value)}
                                        className="code-block"
                                        style={{ width: '100%', minHeight: 400, fontFamily: 'monospace', fontSize: 13, resize: 'vertical' }}
                                        spellCheck={false}
                                    />
                                    <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}>
                                        <button type="button" className="btn-action" onClick={handleSave} disabled={saveStatus === 'saving'}>
                                            {saveStatus === 'saving' ? 'Saving\u2026' : 'Save'}
                                        </button>
                                        <button type="button" className="btn-action" onClick={() => { setEditing(false); setDraft('') }}>Cancel</button>
                                        {saveStatus === 'ok' && <span style={{ color: 'var(--color-success)', fontSize: 13 }}>Saved.</span>}
                                        {saveStatus === 'err' && <span style={{ color: 'var(--color-error)', fontSize: 13 }}>Save failed.</span>}
                                    </div>
                                </>
                            )}
                            {!contentLoading && content === null && <p style={{ color: 'var(--color-text-secondary)' }}>Failed to load content.</p>}
                        </div>
                    </>
                ) : (
                    <div className="empty-state">
                        <h3>Select a memory file</h3>
                    </div>
                )}
            </div>
        </div>
    )
}
