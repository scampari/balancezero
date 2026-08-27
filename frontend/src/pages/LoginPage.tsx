import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { login } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const { setAccessToken } = useAuth()
  const navigate = useNavigate()

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      const { accessToken } = await login(username, password)
      setAccessToken(accessToken)
      navigate('/budget')
    } catch (err) {
      // ApiError's message already carries a sensible fallback (see errorMessage()
      // in client.ts) — no need to duplicate that string here.
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-(--color-bg) px-6">
      <div className="w-full max-w-sm">
        <h1 className="mb-1 text-2xl font-semibold tracking-tight text-(--color-text)">BalanceZero</h1>
        <p className="mb-8 text-sm text-(--color-text-muted)">Zero-based budgeting, built to know where every dollar went.</p>

        <form onSubmit={handleSubmit} className="space-y-4 rounded-xl border border-(--color-border) bg-(--color-surface) p-6">
          {error && (
            <div role="alert" className="rounded-md border border-(--color-negative)/30 bg-(--color-negative)/10 px-3 py-2 text-sm text-(--color-negative)">
              {error}
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="username" className="block text-xs font-medium text-(--color-text-muted)">
              Username
            </label>
            <input
              id="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              autoFocus
              className="w-full rounded-md border border-(--color-border) bg-(--color-bg) px-3 py-2 text-sm text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-faint) focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className="block text-xs font-medium text-(--color-text-muted)">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              className="w-full rounded-md border border-(--color-border) bg-(--color-bg) px-3 py-2 text-sm text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-faint) focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
            />
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-md bg-(--color-accent) px-3 py-2 text-sm font-medium text-(--color-on-accent) transition-colors hover:bg-(--color-accent-hover) disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? 'Logging in…' : 'Log in'}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-(--color-text-faint)">
          Have an invite?{' '}
          <Link to="/signup" className="text-(--color-text-muted) hover:text-(--color-text)">Create an account</Link>
        </p>
        <p className="mt-2 text-center text-xs text-(--color-text-faint)">
          Try the demo account — <span className="text-(--color-text-muted)">demo</span> /{' '}
          <span className="text-(--color-text-muted)">demo-pw</span>
        </p>
      </div>
    </div>
  )
}
