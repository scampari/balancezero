import { type ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { logout } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { ThemePicker } from './ThemePicker'

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive
      ? 'bg-(--color-accent-bg) text-(--color-accent)'
      : 'text-(--color-text-muted) hover:bg-(--color-surface-hover) hover:text-(--color-text)'
  }`

export function AppShell({ children }: { children: ReactNode }) {
  const { accessToken, setAccessToken } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    if (accessToken) await logout(accessToken).catch(() => {})
    setAccessToken(null)
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-svh bg-(--color-bg)">
      <header className="border-b border-(--color-border)">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <span className="text-sm font-semibold tracking-tight text-(--color-text)">BalanceZero</span>
          <nav className="flex items-center gap-1">
            <NavLink to="/budget" className={navLinkClass}>
              Budget
            </NavLink>
            <NavLink to="/transactions" className={navLinkClass}>
              Transactions
            </NavLink>
            <NavLink to="/accounts" className={navLinkClass}>
              Accounts
            </NavLink>
            <span className="ml-2">
              <ThemePicker />
            </span>
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-md px-3 py-1.5 text-sm font-medium text-(--color-text-faint) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text)"
            >
              Log out
            </button>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-6 py-10">{children}</main>
    </div>
  )
}

export function PageLoading() {
  return (
    <div className="flex min-h-svh items-center justify-center bg-(--color-bg)">
      <div className="flex items-center gap-3 text-(--color-text-muted)">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-(--color-border) border-t-(--color-accent)" />
        <span className="text-sm">Loading…</span>
      </div>
    </div>
  )
}
