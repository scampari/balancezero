import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { register } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export function SignupPage() {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const { setAccessToken } = useAuth()
  const navigate = useNavigate()

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      const { accessToken } = await register(username, password, inviteCode, email || undefined)
      setAccessToken(accessToken)
      navigate('/budget')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
      setIsSubmitting(false)
    }
  }

  const inputClass =
    'w-full rounded-md border border-(--color-border) bg-(--color-bg) px-3 py-2 text-sm text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-faint) focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)'
  const labelClass = 'block text-xs font-medium text-(--color-text-muted)'

  return (
    <div className="flex min-h-svh items-center justify-center bg-(--color-bg) px-6">
      <div className="w-full max-w-sm">
        <h1 className="mb-1 text-2xl font-semibold tracking-tight text-(--color-text)">Create your account</h1>
        <p className="mb-8 text-sm text-(--color-text-muted)">BalanceZero is invite-only. Enter your code to get started.</p>

        <form onSubmit={handleSubmit} className="space-y-4 rounded-xl border border-(--color-border) bg-(--color-surface) p-6">
          {error && (
            <div role="alert" className="rounded-md border border-(--color-negative)/30 bg-(--color-negative)/10 px-3 py-2 text-sm text-(--color-negative)">
              {error}
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="username" className={labelClass}>Username</label>
            <input
              id="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              autoFocus
              className={inputClass}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="email" className={labelClass}>Email <span className="text-(--color-text-faint)">(optional)</span></label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              className={inputClass}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className={labelClass}>Password <span className="text-(--color-text-faint)">(at least 10 characters)</span></label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              className={inputClass}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="invite-code" className={labelClass}>Invite code</label>
            <input
              id="invite-code"
              value={inviteCode}
              onChange={(event) => setInviteCode(event.target.value)}
              className={inputClass}
            />
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-md bg-(--color-accent) px-3 py-2 text-sm font-medium text-(--color-on-accent) transition-colors hover:bg-(--color-accent-hover) disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-(--color-text-faint)">
          Already have an account?{' '}
          <Link to="/login" className="text-(--color-text-muted) hover:text-(--color-text)">Log in</Link>
        </p>
      </div>
    </div>
  )
}
