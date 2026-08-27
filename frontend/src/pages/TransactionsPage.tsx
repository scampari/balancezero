import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  type Budget,
  type TransactionEntry,
  getBudgetWithAutoRefresh,
  getTransactionsWithAutoRefresh,
  patchTransactionCategoryWithAutoRefresh,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AppShell, PageLoading } from '../components/AppShell'

function formatMoney(value: string): string {
  return Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

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

  if (!transactions || !categories) return <PageLoading />

  return (
    <AppShell>
      <h1 className="mb-6 text-xl font-semibold tracking-tight text-(--color-text)">Transactions</h1>

      {transactions.length === 0 ? (
        <div className="rounded-xl border border-(--color-border) bg-(--color-surface) px-4 py-10 text-center text-sm text-(--color-text-faint)">
          No transactions this month.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-(--color-border)">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-(--color-border) bg-(--color-surface)">
                <th className="px-4 py-2.5 text-left text-xs font-medium text-(--color-text-muted)">Date</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-(--color-text-muted)">Description</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-(--color-text-muted)">Amount</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-(--color-text-muted)">Category</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-(--color-border)">
              {transactions.map((transaction) => {
                const amount = Number(transaction.amount)
                return (
                  <tr key={transaction.id} className="bg-(--color-surface) transition-colors hover:bg-(--color-surface-hover)">
                    <td className="whitespace-nowrap px-4 py-3 text-(--color-text-muted)">
                      {formatDate(transaction.posted_at)}
                    </td>
                    <td className="px-4 py-3 text-(--color-text)">
                      {transaction.description}
                      {transaction.pending && (
                        <span className="ml-2 rounded-full border border-(--color-border) px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-(--color-text-faint) uppercase">
                          Pending
                        </span>
                      )}
                    </td>
                    <td
                      className={`tabular-nums whitespace-nowrap px-4 py-3 text-right font-medium ${
                        amount < 0 ? 'text-(--color-text)' : 'text-(--color-accent)'
                      }`}
                    >
                      {formatMoney(transaction.amount)}
                    </td>
                    <td className="px-4 py-3">
                      <select
                        value={transaction.category_id ?? ''}
                        onChange={(event) => handleCategoryChange(transaction.id, event.target.value)}
                        className="w-full max-w-40 rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-xs text-(--color-text) outline-none transition-colors focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
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
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </AppShell>
  )
}
