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

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setLoading(true)

    try {
      const response = await fetch(LOGIN_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })

      if (!response.ok) {
        const payload = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
        throw new Error(payload.detail || `HTTP ${response.status}`)
      }

      const user = await response.json()
      login(user)
      navigate('/', { replace: true })
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-shell">
      <div className="login-hero">
        <div className="surface-kicker">Ark-Agentic Studio</div>
        <h1>Mission Control for agent operations, evidence, and direct execution.</h1>
        <p>
          This redesigned Studio moves away from generic admin patterns.
          It is built to manage real agent assets with stronger context, clearer review signals, and better long-form editing surfaces.
        </p>
        <div className="login-signal-grid">
          <div className="login-signal">
            <strong>Control Plane</strong>
            <span>Operational visibility across agents and assets.</span>
          </div>
          <div className="login-signal">
            <strong>Decision Dock</strong>
            <span>Meta-Agent support focused on concrete actions and impact.</span>
          </div>
          <div className="login-signal">
            <strong>Readable Objects</strong>
            <span>Skills, sessions, tools, and memory each have their own working rhythm.</span>
          </div>
        </div>
      </div>

      <form className="login-panel" onSubmit={handleSubmit}>
        <div className="login-panel-header">
          <div className="studio-brand-mark login-brand-mark" />
          <div>
            <strong>Authenticate</strong>
            <span>Enter Studio credentials to continue.</span>
          </div>
        </div>

        {error && <div className="login-error-banner">{error}</div>}

        <label className="form-field">
          <span>Username</span>
          <input
            autoComplete="username"
            autoFocus
            onChange={event => setUsername(event.target.value)}
            placeholder="admin or viewer"
            required
            value={username}
          />
        </label>

        <label className="form-field">
          <span>Password</span>
          <input
            autoComplete="current-password"
            onChange={event => setPassword(event.target.value)}
            placeholder="Enter password"
            required
            type="password"
            value={password}
          />
        </label>

        <button
          className="action-button action-button-primary login-submit"
          disabled={!username.trim() || !password.trim() || loading}
          type="submit"
        >
          {loading ? 'Signing in...' : 'Sign In'}
        </button>

        <div className="login-hints">
          <span>Common roles</span>
          <div className="button-row">
            <div className="status-pill status-healthy">admin</div>
            <div className="status-pill status-watch">viewer</div>
          </div>
        </div>
      </form>
    </div>
  )
}
