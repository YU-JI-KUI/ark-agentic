import { useNavigate } from 'react-router-dom'

export default function DashboardWelcome() {
    const navigate = useNavigate()

    return (
        <div className="gui-content" style={{ padding: 'var(--space-xl)' }}>
            <div className="page-header">
                <h1 style={{ fontSize: '22px', marginBottom: 'var(--space-sm)' }}>Welcome to Ark-Agentic Studio</h1>
                <p style={{ color: 'var(--color-text-secondary)', marginBottom: 'var(--space-xl)' }}>
                    Select an agent from the left to manage its skills, tools, sessions and memory. Or use the Meta-Agent chat on the right to create agents, skills and tools in natural language.
                </p>
            </div>

            <div
                className="metachat-banner"
                onClick={() => navigate('/agents/meta_builder/skills')}
                role="button"
                tabIndex={0}
                onKeyDown={e => e.key === 'Enter' && navigate('/agents/meta_builder/skills')}
            >
                <div className="metachat-banner-icon">🤖</div>
                <div className="metachat-banner-body">
                    <h2>Meta-Agent — Chat to Create</h2>
                    <p>用自然语言创建 Agent、Skill 和 Tool。说 "帮我建一个客服 Agent" 就能开始。</p>
                </div>
                <div className="metachat-banner-arrow">→</div>
            </div>
        </div>
    )
}
