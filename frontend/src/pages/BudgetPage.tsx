import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { type Budget, getBudgetWithAutoRefresh } from '../api/client'
import { useAuth } from '../auth/AuthContext'

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

  if (!budget) return <p>Loading…</p>

  return (
    <div>
      <h1>Budget</h1>
      <nav>
        <Link to="/transactions">Transactions</Link>
      </nav>
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
