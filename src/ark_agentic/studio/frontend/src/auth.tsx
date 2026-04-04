import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

export interface StudioUser {
    user_id: string
    role: 'editor' | 'viewer'
    display_name: string
}

interface AuthContextValue {
    user: StudioUser | null
    login: (user: StudioUser) => void
    logout: () => void
}

const STORAGE_KEY = 'ark_studio_user'

const AuthContext = createContext<AuthContextValue | null>(null)

function loadUser(): StudioUser | null {
    try {
        const raw = localStorage.getItem(STORAGE_KEY)
        return raw ? JSON.parse(raw) : null
    } catch {
        return null
    }
}

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<StudioUser | null>(loadUser)

    const login = useCallback((u: StudioUser) => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(u))
        setUser(u)
    }, [])

    const logout = useCallback(() => {
        localStorage.removeItem(STORAGE_KEY)
        setUser(null)
    }, [])

    return (
        <AuthContext.Provider value={{ user, login, logout }}>
            {children}
        </AuthContext.Provider>
    )
}

export function useAuth(): AuthContextValue {
    const ctx = useContext(AuthContext)
    if (!ctx) throw new Error('useAuth must be used within AuthProvider')
    return ctx
}
