import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { type Budget, getBudgetWithAutoRefresh } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AppShell, PageLoading } from '../components/AppShell'

function formatMoney(value: string): string {
  return Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

export function BudgetPage() {
  const { accessToken, setAccessToken, isAuthChecked } = useAuth()
  const navigate = useNavigate()
  const [budget, setBudget] = useState<Budget | null>(null)

  useEffect(() => {
    let cancelled = false

    // Wait for AuthProvider's initial silent-refresh attempt to resolve
    // before concluding there's no session — accessToken starts null on
    // every mount regardless of whether a valid refresh cookie exists.
    if (!isAuthChecked) return

    if (!accessToken) {
      navigate('/login', { replace: true })
      return
    }

    getBudgetWithAutoRefresh(accessToken, setAccessToken)
      .then((data) => {
        if (!cancelled) setBudget(data)
      })
      .catch(() => {
        // Either not a 401, or refresh itself failed — either way, not
        // recoverable here. Send the user back to login.
        if (!cancelled) {
          setAccessToken(null)
          navigate('/login', { replace: true })
        }
      })

    return () => {
      cancelled = true
    }
  }, [accessToken, isAuthChecked, navigate, setAccessToken])

  if (!budget) return <PageLoading />

  const readyToAssign = Number(budget.ready_to_assign)

  return (
    <AppShell>
      <div className="mb-8 rounded-xl border border-(--color-border) bg-(--color-surface) p-6">
        <p className="text-xs font-medium text-(--color-text-muted)">Ready to Assign</p>
        <p
          data-testid="ready-to-assign"
          className={`tabular-nums mt-1 text-4xl font-semibold tracking-tight ${
            readyToAssign < 0 ? 'text-(--color-negative)' : 'text-(--color-accent)'
          }`}
        >
          {formatMoney(budget.ready_to_assign)}
        </p>
      </div>

      <h2 className="mb-3 text-sm font-medium text-(--color-text-muted)">Categories</h2>
      <div className="overflow-hidden rounded-xl border border-(--color-border)">
        {budget.categories.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-(--color-text-faint)">No categories yet.</p>
        ) : (
          <ul className="divide-y divide-(--color-border)">
            {budget.categories.map((category) => {
              const available = Number(category.available)
              return (
                <li
                  key={category.id}
                  className="flex items-center justify-between bg-(--color-surface) px-4 py-3 transition-colors hover:bg-(--color-surface-hover)"
                >
                  <span className="text-sm text-(--color-text)">{category.name}</span>
                  <div className="text-right">
                    <span
                      className={`tabular-nums text-sm font-medium ${
                        available < 0 ? 'text-(--color-negative)' : 'text-(--color-text)'
                      }`}
                    >
                      {formatMoney(category.available)}
                    </span>
                    <span className="tabular-nums ml-2 text-xs text-(--color-text-faint)">
                      of {formatMoney(category.allocated_this_month)}
                    </span>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </AppShell>
  )
}
