export default function MemoryView() {
    return (
        <div className="master-detail-container">
            {/* Left: Memory Types Menu */}
            <div className="layout-pane-left">
                <div className="list-header">Memory Scopes</div>

                <div className="list-scroll">
                    <div className="list-item active">
                        <div className="list-item-title" style={{ fontFamily: 'monospace' }}>Short-Term Context</div>
                        <div className="list-item-desc">Current session transient memory</div>
                    </div>
                    <div className="list-item" style={{ opacity: 0.5 }}>
                        <div className="list-item-title" style={{ fontFamily: 'monospace' }}>Long-Term Profiles</div>
                        <div className="list-item-desc">User entity extraction (Coming Soon)</div>
                    </div>
                </div>
            </div>

            {/* Right: Memory Detail Area */}
            <div className="layout-pane-main">
                <div className="detail-header">
                    <div className="detail-header-inner">
                        <span className="detail-icon">📚</span>
                        <div>
                            <div className="detail-title" style={{ fontFamily: 'monospace' }}>Short-Term Context</div>
                            <div className="detail-subtitle">Memory Management (Placeholder)</div>
                        </div>
                    </div>
                </div>

                <div className="detail-body">
                    <div className="metadata-card">
                        <div className="metadata-label">Storage Backend</div>
                        <div className="metadata-value">Local file system</div>

                        <div className="metadata-label">Status</div>
                        <div className="metadata-value">
                            <span style={{
                                padding: '2px 8px', borderRadius: 12,
                                background: 'var(--color-warning-light)', color: 'var(--color-warning)',
                                fontSize: 12, fontWeight: 500
                            }}>Not Implemented</span>
                        </div>
                    </div>

                    <h3 className="section-heading">Phase 3 Extension</h3>

                    <div className="placeholder-box">
                        <p style={{ marginBottom: 'var(--space-sm)' }}>Memory CRUD APIs are planned for MVP Phase 3.</p>
                        <p style={{ fontSize: 12, opacity: 0.7 }}>Currently returning 501 Not Implemented API status.</p>
                    </div>
                </div>
            </div>
        </div>
    )
}
