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
import { localDateDaysAgo, localDateKey } from '../lib/dates'

// The transactions list is a rolling window rather than a single calendar
// month, so nothing vanishes when the month rolls over (changes/027).
const ROLLING_WINDOW_DAYS = 60

function formatMoney(value: string): string {
  return Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function todayISO(): string {
  return localDateKey()
}

// Sentinel select value for "To Be Budgeted" — distinct from '' (Uncategorized)
// and from any numeric category id.
const INCOME_OPTION = 'income'

const UNCATEGORIZED_LABEL = 'Uncategorized'
const INCOME_LABEL = 'To Be Budgeted'

// The assignable-category <option> list is identical in the add form and the
// datalist — keep it in one spot.
function CategoryOptionList({ categories }: { categories: Budget['categories'] }) {
  return (
    <>
      {categories.map((category) => (
        <option key={category.id} value={category.id}>
          {category.name}
        </option>
      ))}
    </>
  )
}

// Shared suggestion list for every category combobox on the page.
const CATEGORY_DATALIST_ID = 'bz-category-options'

function CategoryDatalist({ categories }: { categories: Budget['categories'] }) {
  return (
    <datalist id={CATEGORY_DATALIST_ID}>
      <option value={UNCATEGORIZED_LABEL} />
      <option value={INCOME_LABEL} />
      {categories.map((category) => (
        <option key={category.id} value={category.name} />
      ))}
    </datalist>
  )
}

// The raw value handleCategoryChange expects for a transaction's current state.
function rawCategoryValue(t: Pick<TransactionEntry, 'is_income' | 'category_id'>): string {
  if (t.is_income) return INCOME_OPTION
  return t.category_id != null ? String(t.category_id) : ''
}

function categoryDisplay(
  t: Pick<TransactionEntry, 'is_income' | 'category_name'>,
): string {
  if (t.is_income) return INCOME_LABEL
  return t.category_name ?? UNCATEGORIZED_LABEL
}

// An autocompleting text field over the category list, in place of a <select>.
// Free text that doesn't resolve to a known category snaps back to the
// current label on blur.
function CategoryCombobox({
  transaction,
  categories,
  onPick,
  className,
}: {
  transaction: TransactionEntry
  categories: Budget['categories']
  onPick: (raw: string) => void
  className?: string
}) {
  const current = categoryDisplay(transaction)
  const [text, setText] = useState(current)
  useEffect(() => setText(current), [current])

  // Map a label to the raw value handleCategoryChange wants, or null if it
  // isn't a known category.
  function resolve(label: string): string | null {
    const typed = label.trim().toLowerCase()
    if (typed === '' || typed === UNCATEGORIZED_LABEL.toLowerCase()) return ''
    if (typed === INCOME_LABEL.toLowerCase()) return INCOME_OPTION
    const hit = categories.find((c) => c.name.toLowerCase() === typed)
    return hit ? String(hit.id) : null
  }

  function commit(label: string) {
    const raw = resolve(label)
    if (raw === null || raw === rawCategoryValue(transaction)) {
      setText(current) // unknown text or no change — snap back to the label
      return
    }
    onPick(raw)
  }

  return (
    <input
      type="text"
      list={CATEGORY_DATALIST_ID}
      aria-label={`Category for ${transaction.description}`}
      value={text}
      onChange={(e) => {
        const v = e.target.value
        setText(v)
        // an exact hit means they picked from the list — apply right away
        if (resolve(v) !== null && v === v.trim()) commit(v)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
        if (e.key === 'Escape') {
          setText(current)
          e.currentTarget.blur()
        }
      }}
      onBlur={(e) => commit(e.currentTarget.value)}
      className={className}
    />
  )
}

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
        getTransactionsWithAutoRefresh(token, setAccessToken, {
          since: localDateDaysAgo(ROLLING_WINDOW_DAYS),
        }),
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

  // Group categories total their children — a transaction can't be assigned
  // to one (the server rejects it), so keep them out of the pickers.
  const assignableCategories = categories.filter((category) => !category.is_group)

  const inputClass =
    'rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-xs text-(--color-text) outline-none focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)'

  return (
    <AppShell>
      <CategoryDatalist categories={assignableCategories} />
      <div className="mb-6 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-(--color-text)">Transactions</h1>
          <p className="text-xs text-(--color-text-faint)">Last {ROLLING_WINDOW_DAYS} days</p>
        </div>
        <button
          type="button"
          onClick={() => {
            setShowAdd((v) => !v)
            setFormError(null)
          }}
          disabled={accounts.length === 0}
          title={accounts.length === 0 ? 'Connect a bank or add an account first' : undefined}
          className="rounded-md border border-(--color-border) px-3 py-1.5 text-sm font-medium text-(--color-text-muted) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text) disabled:cursor-not-allowed disabled:opacity-60 max-sm:w-full"
        >
          {showAdd ? 'Cancel' : 'Add transaction'}
        </button>
      </div>

      {showAdd && (
        <form
          onSubmit={handleAdd}
          className="mb-4 flex flex-col gap-3 rounded-xl border border-(--color-border) bg-(--color-surface) p-3 sm:flex-row sm:flex-wrap sm:items-end sm:gap-2"
        >
          <label className="flex flex-col gap-1 text-xs text-(--color-text-muted) max-sm:w-full">
            Account
            <select name="account_id" required className={`${inputClass} max-sm:w-full`}>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-(--color-text-muted) max-sm:w-full">
            Date
            <input
              type="date"
              name="posted_at"
              required
              defaultValue={todayISO()}
              className={`${inputClass} max-sm:w-full`}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-(--color-text-muted) max-sm:w-full">
            Amount
            <input
              name="amount"
              required
              inputMode="decimal"
              placeholder="-42.50"
              className={`${inputClass} w-full sm:w-24`}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-(--color-text-muted) max-sm:w-full">
            Description
            <input name="description" required className={`${inputClass} w-full sm:w-48`} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-(--color-text-muted) max-sm:w-full">
            Category
            <select name="category_id" className={`${inputClass} max-sm:w-full`}>
              <option value="">Uncategorized</option>
              <CategoryOptionList categories={assignableCategories} />
            </select>
          </label>
          <button
            type="submit"
            className="rounded-md bg-(--color-accent) px-3 py-1.5 text-xs font-medium text-(--color-on-accent) transition-colors hover:bg-(--color-accent-hover) max-sm:w-full"
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
          No transactions in the last {ROLLING_WINDOW_DAYS} days.
        </div>
      ) : (
        <>
          {/* Desktop: table. Hidden on phones — a 5-column table can't reflow. */}
          <div className="hidden overflow-hidden rounded-xl border border-(--color-border) sm:block">
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
                        {transaction.transfer && (
                          <span
                            title="A movement between your own accounts — not counted as spending"
                            className="ml-2 rounded-full border border-(--color-border) px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-(--color-text-faint) uppercase"
                          >
                            Transfer
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
                        <CategoryCombobox
                          transaction={transaction}
                          categories={assignableCategories}
                          onPick={(raw) => handleCategoryChange(transaction.id, raw)}
                          className="w-full max-w-40 rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-xs text-(--color-text) outline-none transition-colors focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
                        />
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

          {/* Mobile: one card per transaction. */}
          <ul className="space-y-2 sm:hidden">
            {transactions.map((transaction) => {
              const amount = Number(transaction.amount)
              return (
                <li
                  key={transaction.id}
                  className="rounded-xl border border-(--color-border) bg-(--color-surface) p-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm text-(--color-text)">{transaction.description}</p>
                      <p className="mt-0.5 text-xs text-(--color-text-muted)">
                        {formatDate(transaction.posted_at)}
                      </p>
                    </div>
                    <span
                      className={`tabular-nums shrink-0 text-sm font-medium ${
                        amount < 0 ? 'text-(--color-text)' : 'text-(--color-accent)'
                      }`}
                    >
                      {formatMoney(transaction.amount)}
                    </span>
                  </div>

                  {(transaction.pending || transaction.transfer) && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {transaction.pending && (
                        <span className="rounded-full border border-(--color-border) px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-(--color-text-faint) uppercase">
                          Pending
                        </span>
                      )}
                      {transaction.transfer && (
                        <span className="rounded-full border border-(--color-border) px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-(--color-text-faint) uppercase">
                          Transfer
                        </span>
                      )}
                    </div>
                  )}

                  <div className="mt-2 flex items-center gap-2">
                    <CategoryCombobox
                      transaction={transaction}
                      categories={assignableCategories}
                      onPick={(raw) => handleCategoryChange(transaction.id, raw)}
                      className="w-full rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1.5 text-sm text-(--color-text) outline-none transition-colors focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
                    />
                    <button
                      type="button"
                      aria-label={`Delete ${transaction.description}`}
                      onClick={() => handleDelete(transaction.id)}
                      className="shrink-0 rounded px-2 py-1.5 text-sm text-(--color-text-faint) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-negative)"
                    >
                      ✕
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </AppShell>
  )
}
