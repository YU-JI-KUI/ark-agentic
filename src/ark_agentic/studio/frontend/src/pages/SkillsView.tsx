import { useEffect, useState } from 'react'
import { api, type SkillMeta } from '../api'

interface Props { agentId: string }

export default function SkillsView({ agentId }: Props) {
    const [skills, setSkills] = useState<SkillMeta[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selected, setSelected] = useState<SkillMeta | null>(null)

    useEffect(() => {
        setLoading(true)
        setError(null)
        api.listSkills(agentId)
            .then(data => { setSkills(data); setSelected(data[0] || null) })
            .catch(e => setError(e.message))
            .finally(() => setLoading(false))
    }, [agentId])

    if (loading) return <div className="loading"><div className="spinner" /></div>
    if (error) return <div className="empty-state"><h3>⚠️ {error}</h3></div>

    return (
        <div className="master-detail-container">
            {/* Left: Skills Menu */}
            <div className="layout-pane-left">
                <div className="list-header">Configured Skills ({skills.length})</div>

                <div className="list-scroll">
                    {skills.length === 0 ? (
                        <div className="empty-state" style={{ padding: 'var(--space-xl) var(--space-md)' }}>
                            <div className="empty-state-icon" style={{ fontSize: 32 }}>📋</div>
                            <p style={{ fontSize: 13 }}>No skills yet.</p>
                        </div>
                    ) : (
                        skills.map(skill => (
                            <div
                                key={skill.id}
                                className={`list-item ${selected?.id === skill.id ? 'active' : ''}`}
                                onClick={() => setSelected(skill)}
                            >
                                <div className="list-item-title">{skill.name}</div>
                                <div className="list-item-desc">{skill.description || skill.file_path}</div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Right: Skill Detail Area */}
            <div className="layout-pane-main">
                {selected ? (
                    <>
                        <div className="detail-header">
                            <div className="detail-header-inner">
                                <span className="detail-icon">🧠</span>
                                <div>
                                    <div className="detail-title">{selected.name}</div>
                                    <div className="detail-subtitle">{selected.description || 'No description provided'}</div>
                                </div>
                            </div>
                        </div>

                        <div className="detail-body">
                            <div className="metadata-card">
                                <div className="metadata-label">SKILL ID</div>
                                <div className="metadata-value">{selected.id}</div>
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
                        <h3>Select a skill to view its configuration</h3>
                    </div>
                )}
            </div>
        </div>
    )
}
