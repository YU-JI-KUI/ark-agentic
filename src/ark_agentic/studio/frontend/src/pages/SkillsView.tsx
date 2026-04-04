import { useEffect, useState, useCallback } from 'react'
import { api, type SkillMeta } from '../api'
import { useAuth } from '../auth'

interface Props { agentId: string }

type Mode = 'view' | 'create' | 'edit'

export default function SkillsView({ agentId }: Props) {
    const { user } = useAuth()
    const isEditor = user?.role === 'editor'
    const [skills, setSkills] = useState<SkillMeta[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selected, setSelected] = useState<SkillMeta | null>(null)
    const [mode, setMode] = useState<Mode>('view')
    const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)
    const [confirmDelete, setConfirmDelete] = useState(false)

    // Form state
    const [formName, setFormName] = useState('')
    const [formDesc, setFormDesc] = useState('')
    const [formContent, setFormContent] = useState('')

    const showToast = useCallback((msg: string, type: 'success' | 'error' = 'success') => {
        setToast({ msg, type })
        setTimeout(() => setToast(null), 3000)
    }, [])

    const reload = useCallback(() => {
        setLoading(true)
        api.listSkills(agentId)
            .then(data => { setSkills(data); if (!selected) setSelected(data[0] || null) })
            .catch(e => setError(e.message))
            .finally(() => setLoading(false))
    }, [agentId, selected])

    useEffect(() => { reload() }, [agentId])

    const enterCreate = () => {
        setMode('create'); setFormName(''); setFormDesc(''); setFormContent('')
        setSelected(null)
    }

    const enterEdit = () => {
        if (!selected) return
        setMode('edit')
        setFormName(selected.name)
        setFormDesc(selected.description)
        setFormContent(selected.content)
    }

    const cancelForm = () => { setMode('view') }

    const handleCreate = async () => {
        try {
            const meta = await api.createSkill(agentId, {
                name: formName, description: formDesc, content: formContent,
            })
            showToast(`Skill "${meta.name}" created`)
            setMode('view')
            reload()
            setSelected(meta)
        } catch (e: any) { showToast(e.message, 'error') }
    }

    const handleUpdate = async () => {
        if (!selected) return
        try {
            const meta = await api.updateSkill(agentId, selected.id, {
                name: formName, description: formDesc, content: formContent,
            })
            showToast(`Skill "${meta.name}" updated`)
            setMode('view')
            setSelected(meta)
            reload()
        } catch (e: any) { showToast(e.message, 'error') }
    }

    const handleDelete = async () => {
        if (!selected) return
        try {
            await api.deleteSkill(agentId, selected.id)
            showToast(`Skill "${selected.name}" deleted`)
            setConfirmDelete(false)
            setSelected(null)
            reload()
        } catch (e: any) { showToast(e.message, 'error') }
    }

    if (loading) return <div className="loading"><div className="spinner" /></div>
    if (error) return <div className="empty-state"><h3>⚠️ {error}</h3></div>

    return (
        <div className="master-detail-container">
            {/* Left: Skills Menu */}
            <div className="layout-pane-left">
                <div className="list-header">Skills ({skills.length})</div>
                {isEditor && <button className="btn-create" onClick={enterCreate}>＋ New Skill</button>}

                <div className="list-scroll">
                    {skills.length === 0 && mode !== 'create' ? (
                        <div className="empty-state" style={{ padding: 'var(--space-xl) var(--space-md)' }}>
                            <div className="empty-state-icon" style={{ fontSize: 32 }}>📋</div>
                            <p style={{ fontSize: 13 }}>No skills yet.</p>
                        </div>
                    ) : (
                        skills.map(skill => (
                            <div
                                key={skill.id}
                                className={`list-item ${selected?.id === skill.id && mode === 'view' ? 'active' : ''}`}
                                onClick={() => { setSelected(skill); setMode('view') }}
                            >
                                <div className="list-item-title">{skill.name}</div>
                                <div className="list-item-desc">{skill.description || skill.file_path}</div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Right: Detail / Form Area */}
            <div className="layout-pane-main">
                {mode === 'create' || mode === 'edit' ? (
                    /* ── Create / Edit Form ─── */
                    <>
                        <div className="detail-header">
                            <div className="detail-header-inner">
                                <span className="detail-icon">{mode === 'create' ? '✨' : '✏️'}</span>
                                <div>
                                    <div className="detail-title">{mode === 'create' ? 'New Skill' : `Edit: ${selected?.name}`}</div>
                                    <div className="detail-subtitle">{mode === 'create' ? 'Create a new skill with instructions' : 'Modify skill metadata and content'}</div>
                                </div>
                            </div>
                        </div>
                        <div className="detail-body">
                            <div className="form-group">
                                <label className="form-label">Name</label>
                                <input className="form-input" value={formName}
                                    onChange={e => setFormName(e.target.value)}
                                    placeholder="e.g. 需求澄清" />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Description</label>
                                <input className="form-input" value={formDesc}
                                    onChange={e => setFormDesc(e.target.value)}
                                    placeholder="Brief description of this skill" />
                            </div>
                            <div className="form-group">
                                <label className="form-label">Content (SKILL.md Body)</label>
                                <textarea className="form-textarea" value={formContent}
                                    onChange={e => setFormContent(e.target.value)}
                                    placeholder="# Skill Instructions&#10;&#10;Write your skill rules and guidelines here..." />
                            </div>
                            <div style={{ display: 'flex', gap: 8 }}>
                                <button className="btn-save"
                                    onClick={mode === 'create' ? handleCreate : handleUpdate}
                                    disabled={!formName.trim()}>
                                    {mode === 'create' ? '✓ Create' : '✓ Save'}
                                </button>
                                <button className="btn-action" onClick={cancelForm}>Cancel</button>
                            </div>
                        </div>
                    </>
                ) : selected ? (
                    /* ── View Mode ─── */
                    <>
                        <div className="detail-header">
                            <div className="detail-header-inner" style={{ flex: 1 }}>
                                <span className="detail-icon">🧠</span>
                                <div style={{ flex: 1 }}>
                                    <div className="detail-title">{selected.name}</div>
                                    <div className="detail-subtitle">{selected.description || 'No description provided'}</div>
                                </div>
                                {isEditor && (
                                <div className="detail-actions">
                                    <button className="btn-action" onClick={enterEdit}>
                                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /><path d="m15 5 4 4" /></svg>
                                        Edit
                                    </button>
                                    <button className="btn-action btn-danger" onClick={() => setConfirmDelete(true)}>
                                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" /><line x1="10" x2="10" y1="11" y2="17" /><line x1="14" x2="14" y1="11" y2="17" /></svg>
                                        Delete
                                    </button>
                                </div>
                                )}
                            </div>
                        </div>

                        <div className="detail-body">
                            <div className="metadata-card" style={{ display: 'grid', gridTemplateColumns: 'minmax(100px, max-content) 1fr', gap: '8px 16px', alignItems: 'center' }}>
                                <div className="metadata-label">SKILL ID</div>
                                <div className="metadata-value">{selected.id}</div>

                                {selected.version && (
                                    <>
                                        <div className="metadata-label">Version</div>
                                        <div className="metadata-value">{selected.version}</div>
                                    </>
                                )}
                                {selected.invocation_policy && (
                                    <>
                                        <div className="metadata-label">Policy</div>
                                        <div className="metadata-value">
                                            <span style={{ padding: '2px 8px', borderRadius: 12, background: 'var(--color-primary-light)', color: 'var(--color-primary)', fontSize: 12, fontWeight: 500 }}>
                                                {selected.invocation_policy}
                                            </span>
                                        </div>
                                    </>
                                )}
                                {selected.group && (
                                    <>
                                        <div className="metadata-label">Group</div>
                                        <div className="metadata-value">{selected.group}</div>
                                    </>
                                )}
                                {selected.tags && selected.tags.length > 0 && (
                                    <>
                                        <div className="metadata-label">Tags</div>
                                        <div className="metadata-value" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                                            {selected.tags.map(t => (
                                                <span key={t} style={{ padding: '2px 8px', borderRadius: 4, background: '#F3F4F6', color: '#4B5563', fontSize: 12, border: '1px solid #E5E7EB' }}>
                                                    {t}
                                                </span>
                                            ))}
                                        </div>
                                    </>
                                )}

                                <div className="metadata-label">File Path</div>
                                <div className="metadata-value">{selected.file_path}</div>
                            </div>

                            <h3 className="section-heading">Prompt &amp; Guidelines</h3>
                            <div className="code-block" style={{ fontSize: 14 }}>
                                {selected.content || 'File is empty'}
                            </div>
                        </div>
                    </>
                ) : (
                    <div className="empty-state">
                        <div className="empty-state-icon">👈</div>
                        <h3>Select a skill or create a new one</h3>
                    </div>
                )}
            </div>

            {/* Confirm Delete Dialog */}
            {confirmDelete && (
                <div className="dialog-overlay" onClick={() => setConfirmDelete(false)}>
                    <div className="dialog-box" onClick={e => e.stopPropagation()}>
                        <h3>Delete Skill</h3>
                        <p>Are you sure you want to delete "<strong>{selected?.name}</strong>"? This will remove the entire skill directory and cannot be undone.</p>
                        <div className="dialog-actions">
                            <button className="btn-action" onClick={() => setConfirmDelete(false)}>Cancel</button>
                            <button className="btn-action btn-danger" onClick={handleDelete}>Delete</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Toast */}
            {toast && <div className={`toast toast-${toast.type}`}>{toast.msg}</div>}
        </div>
    )
}
