import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { type Budget, ApiError, getBudget, refresh } from '../api/client'
import { useAuth } from '../auth/AuthContext'

export function BudgetPage() {
  const { accessToken, setAccessToken } = useAuth()
  const navigate = useNavigate()
  const [budget, setBudget] = useState<Budget | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      if (!accessToken) {
        navigate('/login', { replace: true })
        return
      }
      try {
        const data = await getBudget(accessToken)
        if (!cancelled) setBudget(data)
      } catch (err) {
        // Expired access token: refresh once using the httpOnly cookie and
        // retry, rather than bouncing the user to login for a routine expiry.
        if (err instanceof ApiError && err.status === 401) {
          const refreshed = await refresh()
          if (refreshed && !cancelled) {
            setAccessToken(refreshed.accessToken) // effect re-runs with the new token
            return
          }
        }
        if (!cancelled) {
          setAccessToken(null)
          navigate('/login', { replace: true })
        }
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [accessToken, navigate, setAccessToken])

  if (!budget) return <p>Loading…</p>

  return (
    <div>
      <h1>Budget</h1>
      <p>Ready to Assign</p>
      <p>${Number(budget.ready_to_assign).toFixed(2)}</p>
      <ul>
        {budget.categories.map((category) => (
          <li key={category.id}>
            {category.name}: ${Number(category.allocated_this_month).toFixed(2)}
          </li>
        ))}
      </ul>
    </div>
  )
}
