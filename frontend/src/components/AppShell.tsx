import { type ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { logout } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { ThemePicker } from './ThemePicker'

const NAV_ITEMS = [
  { to: '/budget', label: 'Budget' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/accounts', label: 'Accounts' },
  { to: '/reports', label: 'Reports' },
] as const

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive
      ? 'bg-(--color-accent-bg) text-(--color-accent)'
      : 'text-(--color-text-muted) hover:bg-(--color-surface-hover) hover:text-(--color-text)'
  }`

// Bottom tab bar (mobile only). Larger hit area, no hover state — touch has none.
const tabLinkClass = ({ isActive }: { isActive: boolean }) =>
  `flex flex-col items-center justify-center gap-0.5 py-2 text-xs font-medium tracking-tight transition-colors ${
    isActive ? 'text-(--color-accent)' : 'text-(--color-text-muted)'
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
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-3 sm:px-6 sm:py-4">
          <span className="text-sm font-semibold tracking-tight text-(--color-text)">BalanceZero</span>

          {/* Desktop: full nav inline */}
          <nav className="hidden items-center gap-1 sm:flex">
            {NAV_ITEMS.map((item) => (
              <NavLink key={item.to} to={item.to} className={navLinkClass}>
                {item.label}
              </NavLink>
            ))}
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

          {/* Mobile: navigation lives in the bottom tab bar; this menu holds
              the low-frequency controls (theme, log out). */}
          <details className="relative sm:hidden">
            <summary className="flex h-9 w-9 cursor-pointer list-none items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--color-surface-hover) [&::-webkit-details-marker]:hidden">
              <span aria-hidden className="text-lg leading-none">⋯</span>
              <span className="sr-only">More</span>
            </summary>
            <div className="absolute right-0 z-30 mt-1 flex w-44 flex-col gap-2 rounded-md border border-(--color-border) bg-(--color-surface) p-3 shadow-lg">
              <ThemePicker />
              <button
                type="button"
                onClick={handleLogout}
                className="rounded-md px-3 py-2 text-left text-sm font-medium text-(--color-text-muted) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text)"
              >
                Log out
              </button>
            </div>
          </details>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 pt-6 pb-24 sm:px-6 sm:pt-10 sm:pb-10">{children}</main>

      {/* Bottom tab bar — mobile only. pb env() clears the iOS home indicator. */}
      <nav
        aria-label="Primary"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-(--color-border) bg-(--color-surface) pb-[env(safe-area-inset-bottom)] sm:hidden"
      >
        {NAV_ITEMS.map((item) => (
          <NavLink key={item.to} to={item.to} className={tabLinkClass}>
            {item.label}
          </NavLink>
        ))}
      </nav>
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
