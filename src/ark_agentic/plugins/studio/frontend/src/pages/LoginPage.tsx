import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth'
import ThemeToggle from '../components/ThemeToggle'
import { SparkIcon } from '../components/StudioIcons'

const LOGIN_URL = '/api/studio/auth/login'

function safeNextPath(value: string | null): string {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return '/'
  if (value === '/login' || value.startsWith('/login?')) return '/'
  return value
}

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
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
      navigate(safeNextPath(searchParams.get('next')), { replace: true })
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-shell">
      <div className="login-theme-toggle">
        <ThemeToggle />
      </div>
      <div className="login-container">
        <div className="login-hero">
          <div className="login-hero-inner">
            <div className="login-brand">
              <div className="studio-brand-mark">
                <SparkIcon />
              </div>
              <span>Ark-Agentic Studio</span>
            </div>
            <div className="login-headline">
              <div className="login-eyebrow">Agent Operations Platform</div>
              <h1 className="login-h1">
                Build, run, and govern <em>autonomous agents</em>.
              </h1>
              <p className="login-lede">
                从 Skill 设计、Tool 注册，到生产会话回放与审计 —— 把 LLM
                agent 的整个生命周期收敛到一个工作台。
              </p>
            </div>
            <div className="login-foot">
              <span>© 2026 Ark Platform Group</span>
            </div>
          </div>
        </div>

        <form className="login-panel" onSubmit={handleSubmit}>
          <div className="login-panel-header">
            <strong>Welcome back</strong>
            <span>Sign in to your Ark-Agentic workspace.</span>
          </div>

          {error && <div className="login-error-banner">{error}</div>}

          <label className="form-field">
            <span>用户名</span>
            <input
              autoComplete="username"
              autoFocus
              onChange={event => setUsername(event.target.value)}
              placeholder="请输入用户名"
              required
              value={username}
            />
          </label>

          <label className="form-field">
            <span>密码</span>
            <input
              autoComplete="current-password"
              onChange={event => setPassword(event.target.value)}
              placeholder="请输入密码"
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
            {loading ? '登录中...' : '登录'}
          </button>
        </form>
      </div>
    </div>
  )
}
