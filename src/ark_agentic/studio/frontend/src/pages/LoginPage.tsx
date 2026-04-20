import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { SparkIcon } from '../components/StudioIcons'

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
      <div className="login-container">
        <div className="login-hero">
          <div className="surface-kicker">Ark-Agentic Studio</div>
          <div className="login-signal-grid">
            <div className="login-signal">
              <strong>统一控制台</strong>
              <span>集中查看 Agent、Skills、Tools、Sessions 与 Memory。</span>
            </div>
            <div className="login-signal">
              <strong>调试工作流</strong>
              <span>围绕真实运行记录与资产状态，快速定位问题并推进修改。</span>
            </div>
            <div className="login-signal">
              <strong>可视化视角</strong>
              <span>让复杂对象以更清晰的结构呈现，降低运营与维护成本。</span>
            </div>
          </div>
        </div>

        <form className="login-panel" onSubmit={handleSubmit}>
          <div className="login-panel-header">
            <div className="studio-brand-mark">
              <SparkIcon />
            </div>
            <div>
              <strong>登录 Studio</strong>
            </div>
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
