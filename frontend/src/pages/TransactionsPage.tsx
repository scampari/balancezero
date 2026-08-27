import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  type Account,
  type Budget,
  type TransactionEntry,
  createTransactionWithAutoRefresh,
  deleteTransactionWithAutoRefresh,
  getBudgetWithAutoRefresh,
  getTransactionsWithAutoRefresh,
  listAccountsWithAutoRefresh,
  markTransactionIncomeWithAutoRefresh,
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

function todayISO(): string {
  return new Date().toISOString().slice(0, 10)
}

// Sentinel select value for "To Be Budgeted" — distinct from '' (Uncategorized)
// and from any numeric category id.
const INCOME_OPTION = 'income'

export function TransactionsPage() {
  const { accessToken, setAccessToken, isAuthChecked } = useAuth()
  const navigate = useNavigate()
  const [transactions, setTransactions] = useState<TransactionEntry[] | null>(null)
  const [categories, setCategories] = useState<Budget['categories'] | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const load = useCallback(
    (token: string) =>
      Promise.all([
        getTransactionsWithAutoRefresh(token, setAccessToken),
        getBudgetWithAutoRefresh(token, setAccessToken),
        listAccountsWithAutoRefresh(token, setAccessToken),
      ]).then(([transactionsData, budgetData, accountsData]) => {
        setTransactions(transactionsData.transactions)
        setCategories(budgetData.categories)
        setAccounts(accountsData.accounts)
      }),
    [setAccessToken],
  )

  useEffect(() => {
    let cancelled = false
    if (!isAuthChecked) return
    if (!accessToken) {
      navigate('/login', { replace: true })
      return
    }
    load(accessToken).catch(() => {
      if (!cancelled) {
        setAccessToken(null)
        navigate('/login', { replace: true })
      }
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, isAuthChecked, navigate, setAccessToken])

  async function handleCategoryChange(transactionId: number, rawValue: string) {
    if (!accessToken || !transactions) return
    const updated =
      rawValue === INCOME_OPTION
        ? await markTransactionIncomeWithAutoRefresh(accessToken, setAccessToken, transactionId)
        : await patchTransactionCategoryWithAutoRefresh(
            accessToken,
            setAccessToken,
            transactionId,
            rawValue === '' ? null : Number(rawValue),
          )
    setTransactions(
      transactions.map((t) =>
        t.id === transactionId
          ? { ...t, category_id: updated.category_id, category_name: updated.category_name, is_income: updated.is_income }
          : t,
      ),
    )
  }

  async function handleDelete(transactionId: number) {
    if (!accessToken || !transactions) return
    await deleteTransactionWithAutoRefresh(accessToken, setAccessToken, transactionId)
    setTransactions(transactions.filter((t) => t.id !== transactionId))
  }

  async function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!accessToken) return
    const form = new FormData(event.currentTarget)
    setFormError(null)
    try {
      await createTransactionWithAutoRefresh(accessToken, setAccessToken, {
        account_id: Number(form.get('account_id')),
        posted_at: String(form.get('posted_at')),
        amount: String(form.get('amount')),
        description: String(form.get('description')),
        category_id: form.get('category_id') ? Number(form.get('category_id')) : null,
      })
      setShowAdd(false)
      await load(accessToken)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Could not add the transaction.')
    }
  }

  if (!transactions || !categories) return <PageLoading />

  const inputClass =
    'rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-xs text-(--color-text) outline-none focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)'

  return (
    <AppShell>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight text-(--color-text)">Transactions</h1>
        <button
          type="button"
          onClick={() => {
            setShowAdd((v) => !v)
            setFormError(null)
          }}
          disabled={accounts.length === 0}
          title={accounts.length === 0 ? 'Connect a bank or add an account first' : undefined}
          className="rounded-md border border-(--color-border) px-3 py-1.5 text-sm font-medium text-(--color-text-muted) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text) disabled:cursor-not-allowed disabled:opacity-60"
        >
          {showAdd ? 'Cancel' : 'Add transaction'}
        </button>
      </div>

      {showAdd && (
        <form
          onSubmit={handleAdd}
          className="mb-4 flex flex-wrap items-end gap-2 rounded-xl border border-(--color-border) bg-(--color-surface) p-3"
        >
          <label className="flex flex-col gap-1 text-xs text-(--color-text-muted)">
            Account
            <select name="account_id" required className={inputClass}>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-(--color-text-muted)">
            Date
            <input type="date" name="posted_at" required defaultValue={todayISO()} className={inputClass} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-(--color-text-muted)">
            Amount
            <input
              name="amount"
              required
              inputMode="decimal"
              placeholder="-42.50"
              className={`${inputClass} w-24`}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-(--color-text-muted)">
            Description
            <input name="description" required className={`${inputClass} w-48`} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-(--color-text-muted)">
            Category
            <select name="category_id" className={inputClass}>
              <option value="">Uncategorized</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="rounded-md bg-(--color-accent) px-3 py-1.5 text-xs font-medium text-(--color-on-accent) transition-colors hover:bg-(--color-accent-hover)"
          >
            Add
          </button>
          {formError && <p role="alert" className="w-full text-xs text-(--color-negative)">{formError}</p>}
          <p className="w-full text-xs text-(--color-text-faint)">
            Negative amounts are spending, positive are inflow.
          </p>
        </form>
      )}

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
                <th className="px-4 py-2.5" />
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
                        value={transaction.is_income ? INCOME_OPTION : (transaction.category_id ?? '')}
                        onChange={(event) => handleCategoryChange(transaction.id, event.target.value)}
                        className="w-full max-w-40 rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-xs text-(--color-text) outline-none transition-colors focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
                      >
                        <option value="">Uncategorized</option>
                        <option value={INCOME_OPTION}>To Be Budgeted</option>
                        {categories.map((category) => (
                          <option key={category.id} value={category.id}>
                            {category.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-2 py-3 text-right">
                      <button
                        type="button"
                        aria-label={`Delete ${transaction.description}`}
                        onClick={() => handleDelete(transaction.id)}
                        className="rounded px-2 py-1 text-xs text-(--color-text-faint) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-negative)"
                      >
                        ✕
                      </button>
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
