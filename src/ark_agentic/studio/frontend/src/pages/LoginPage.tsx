import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'

const LOGIN_URL = '/api/studio/auth/login'

export default function LoginPage() {
    const { login } = useAuth()
    const navigate = useNavigate()
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [error, setError] = useState('')
    const [loading, setLoading] = useState(false)

    async function handleSubmit(e: FormEvent) {
        e.preventDefault()
        setError('')
        setLoading(true)

        try {
            const res = await fetch(LOGIN_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            })
            if (!res.ok) {
                const data = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
                throw new Error(data.detail || `HTTP ${res.status}`)
            }
            const user = await res.json()
            login(user)
            navigate('/', { replace: true })
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="login-page">
            <form className="login-card" onSubmit={handleSubmit}>
                <div className="login-brand">
                    <div className="login-logo">A</div>
                    <h1 className="login-title">Ark-Agentic Studio</h1>
                    <p className="login-subtitle">Agent Development Console</p>
                </div>

                {error && <div className="login-error">{error}</div>}

                <div className="login-field">
                    <label className="login-label" htmlFor="username">Username</label>
                    <input
                        id="username"
                        className="login-input"
                        type="text"
                        value={username}
                        onChange={e => setUsername(e.target.value)}
                        placeholder="Enter username"
                        autoComplete="username"
                        autoFocus
                        required
                    />
                </div>

                <div className="login-field">
                    <label className="login-label" htmlFor="password">Password</label>
                    <input
                        id="password"
                        className="login-input"
                        type="password"
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        placeholder="Enter password"
                        autoComplete="current-password"
                        required
                    />
                </div>

                <button
                    className="login-submit"
                    type="submit"
                    disabled={loading || !username.trim() || !password.trim()}
                >
                    {loading ? 'Signing in...' : 'Sign In'}
                </button>

                <div className="login-hint">
                    <span className="login-hint-badge login-hint-editor">admin</span>
                    <span className="login-hint-sep">/</span>
                    <span className="login-hint-badge login-hint-viewer">viewer</span>
                </div>
            </form>
        </div>
    )
}
