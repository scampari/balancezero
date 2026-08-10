import { createContext, useContext, useState, type ReactNode } from 'react'

interface AuthContextValue {
  accessToken: string | null
  setAccessToken: (token: string | null) => void
}

// Deliberately React state only — never localStorage/sessionStorage. See
// spec/frontend-app.md and context/security-requirements.md: an XSS bug
// shouldn't be able to read a persisted token, so nothing persists it.
const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(null)
  return <AuthContext.Provider value={{ accessToken, setAccessToken }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
