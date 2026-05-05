import { useEffect, useState } from 'react'
import { MoonIcon, SunIcon } from './StudioIcons'

type Theme = 'light' | 'dark'

const STORAGE_KEY = 'ark-studio-theme'

function readInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'light'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) return 'dark'
  return 'light'
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
}

if (typeof window !== 'undefined') {
  applyTheme(readInitialTheme())
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => readInitialTheme())

  useEffect(() => {
    applyTheme(theme)
    window.localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  const next: Theme = theme === 'light' ? 'dark' : 'light'

  return (
    <button
      aria-label={`Switch to ${next} theme`}
      className="theme-toggle-button"
      onClick={() => setTheme(next)}
      title={`Switch to ${next} theme`}
      type="button"
    >
      {theme === 'light' ? <MoonIcon /> : <SunIcon />}
    </button>
  )
}
