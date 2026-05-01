import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'
import { api } from './api'

export type StudioRole = 'admin' | 'editor' | 'viewer'

export interface StudioUser {
    user_id: string
    role: StudioRole
    display_name: string
    token: string
    token_id: string
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
        if (!raw) return null
        const parsed = JSON.parse(raw) as Partial<StudioUser>
        if (
            typeof parsed.user_id !== 'string' ||
            typeof parsed.display_name !== 'string' ||
            typeof parsed.token !== 'string' ||
            typeof parsed.token_id !== 'string' ||
            !isStudioRole(parsed.role)
        ) {
            return null
        }
        return parsed as StudioUser
    } catch {
        return null
    }
}

function isStudioRole(value: unknown): value is StudioRole {
    return value === 'admin' || value === 'editor' || value === 'viewer'
}

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<StudioUser | null>(loadUser)

    const login = useCallback((u: StudioUser) => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(u))
        setUser(u)
    }, [])

    const logout = useCallback(() => {
        void api.logout().catch(() => undefined)
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

export function canEditStudio(role: StudioRole | undefined | null): boolean {
    return role === 'admin' || role === 'editor'
}

export function canManageUsers(role: StudioRole | undefined | null): boolean {
    return role === 'admin'
}
