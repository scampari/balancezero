import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { refresh } from '../api/client'

interface AuthContextValue {
  accessToken: string | null
  setAccessToken: (token: string | null) => void
  // True once the initial silent-refresh attempt (on app mount) has resolved,
  // one way or the other. Pages should wait for this before concluding
  // "no token = not logged in" and redirecting — accessToken starts null on
  // every mount (nothing persists it), so without this a valid session would
  // get bounced to /login on every page reload before the refresh had a
  // chance to run.
  isAuthChecked: boolean
}

// Deliberately React state only — never localStorage/sessionStorage. See
// spec/frontend-app.md and context/security-requirements.md: an XSS bug
// shouldn't be able to read a persisted token, so nothing persists it.
const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [isAuthChecked, setIsAuthChecked] = useState(false)
  // Guards against React StrictMode's dev-only double-invoke of effects.
  // Without this, two concurrent /api/refresh calls would race against the
  // same one-time-use rotating refresh cookie — one succeeds and rotates it,
  // the other then 401s on the now-stale cookie, and whichever result lands
  // second (not necessarily the real one) would win. The ref ensures the
  // actual network call only ever fires once per true mount.
  const hasAttemptedRefresh = useRef(false)

  useEffect(() => {
    if (hasAttemptedRefresh.current) return
    hasAttemptedRefresh.current = true

    refresh().then((result) => {
      if (result) setAccessToken(result.accessToken)
      setIsAuthChecked(true)
    })
  }, [])

  const value = useMemo(() => ({ accessToken, setAccessToken, isAuthChecked }), [accessToken, isAuthChecked])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
