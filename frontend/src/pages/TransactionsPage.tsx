import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  type Budget,
  type TransactionEntry,
  getBudgetWithAutoRefresh,
  getTransactionsWithAutoRefresh,
  patchTransactionCategoryWithAutoRefresh,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'

export function TransactionsPage() {
  const { accessToken, setAccessToken, isAuthChecked } = useAuth()
  const navigate = useNavigate()
  const [transactions, setTransactions] = useState<TransactionEntry[] | null>(null)
  const [categories, setCategories] = useState<Budget['categories'] | null>(null)

  useEffect(() => {
    let cancelled = false

    if (!isAuthChecked) return

    if (!accessToken) {
      navigate('/login', { replace: true })
      return
    }

    Promise.all([
      getTransactionsWithAutoRefresh(accessToken, setAccessToken),
      getBudgetWithAutoRefresh(accessToken, setAccessToken),
    ])
      .then(([transactionsData, budgetData]) => {
        if (!cancelled) {
          setTransactions(transactionsData.transactions)
          setCategories(budgetData.categories)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAccessToken(null)
          navigate('/login', { replace: true })
        }
      })

    return () => {
      cancelled = true
    }
  }, [accessToken, isAuthChecked, navigate, setAccessToken])

  async function handleCategoryChange(transactionId: number, rawValue: string) {
    if (!accessToken || !transactions) return
    const categoryId = rawValue === '' ? null : Number(rawValue)
    const updated = await patchTransactionCategoryWithAutoRefresh(
      accessToken,
      setAccessToken,
      transactionId,
      categoryId,
    )
    setTransactions(
      transactions.map((t) =>
        t.id === transactionId
          ? { ...t, category_id: updated.category_id, category_name: updated.category_name }
          : t,
      ),
    )
  }

  if (!transactions || !categories) return <p>Loading…</p>

  return (
    <div>
      <h1>Transactions</h1>
      <nav>
        <Link to="/budget">Budget</Link>
      </nav>
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Description</th>
            <th>Amount</th>
            <th>Category</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((transaction) => (
            <tr key={transaction.id}>
              <td>{transaction.posted_at}</td>
              <td>{transaction.description}</td>
              <td>{transaction.amount}</td>
              <td>
                <select
                  value={transaction.category_id ?? ''}
                  onChange={(event) => handleCategoryChange(transaction.id, event.target.value)}
                >
                  <option value="">Uncategorized</option>
                  {categories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
