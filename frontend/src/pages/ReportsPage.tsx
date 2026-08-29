import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  type Account,
  type Budget,
  type PlaidInstitution,
  type ReportGrain,
  type ReportsResponse,
  getBudgetWithAutoRefresh,
  getPlaidStatusWithAutoRefresh,
  getReportsWithAutoRefresh,
  listAccountsWithAutoRefresh,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AppShell, PageLoading } from '../components/AppShell'
import { HBarList } from '../components/charts/HBarList'
import { MonthBars } from '../components/charts/MonthBars'
import { type Grain, bucketLabel, formatMoney, shortMonth } from '../components/charts/chartScale'

function monthKey(offsetFromNow: number): string {
  const now = new Date()
  const d = new Date(now.getFullYear(), now.getMonth() - offsetFromNow, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

// Last 18 months, newest first — enough for the pickers without hitting the
// backend's 24-month cap.
const MONTH_OPTIONS = Array.from({ length: 18 }, (_, i) => monthKey(i))

const GRAINS: ReportGrain[] = ['week', 'month', 'quarter', 'year']

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-(--color-border) bg-(--color-surface) p-4">
      <h2 className="mb-3 text-sm font-medium text-(--color-text-muted)">{title}</h2>
      {children}
    </section>
  )
}

function parseIds(raw: string | null): number[] {
  if (!raw) return []
  return raw
    .split(',')
    .map(Number)
    .filter((n) => Number.isInteger(n) && n > 0)
}

export function ReportsPage() {
  const { accessToken, setAccessToken, isAuthChecked } = useAuth()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const from = searchParams.get('from') ?? monthKey(5)
  const to = searchParams.get('to') ?? monthKey(0)
  const grain = (searchParams.get('grain') as ReportGrain) ?? 'month'
  const accountIds = useMemo(() => parseIds(searchParams.get('accounts')), [searchParams])
  const categoryIds = useMemo(() => parseIds(searchParams.get('categories')), [searchParams])
  const excludeTransfers = searchParams.get('transfers') !== 'include'

  const [report, setReport] = useState<ReportsResponse | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [institutions, setInstitutions] = useState<PlaidInstitution[]>([])
  const [categories, setCategories] = useState<Budget['categories']>([])
  const [error, setError] = useState<string | null>(null)

  // One-time load of the filter option lists.
  useEffect(() => {
    if (!accessToken) return
    Promise.all([
      listAccountsWithAutoRefresh(accessToken, setAccessToken),
      getPlaidStatusWithAutoRefresh(accessToken, setAccessToken),
      getBudgetWithAutoRefresh(accessToken, setAccessToken),
    ])
      .then(([accountsData, statusData, budgetData]) => {
        setAccounts(accountsData.accounts)
        setInstitutions(statusData.items)
        setCategories(budgetData.categories)
      })
      .catch(() => {
        /* filter lists are best-effort — the report itself still loads */
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken])

  const load = useCallback(
    (token: string) =>
      getReportsWithAutoRefresh(token, setAccessToken, {
        from,
        to,
        grain,
        accounts: accountIds,
        categories: categoryIds,
        excludeTransfers,
      }).then(setReport),
    [setAccessToken, from, to, grain, accountIds, categoryIds, excludeTransfers],
  )

  useEffect(() => {
    let cancelled = false
    if (!isAuthChecked) return
    if (!accessToken) {
      navigate('/login', { replace: true })
      return
    }
    setError(null)
    load(accessToken).catch((err) => {
      if (cancelled) return
      if (err && typeof err === 'object' && 'status' in err && err.status === 401) {
        setAccessToken(null)
        navigate('/login', { replace: true })
      } else {
        setError(err instanceof Error ? err.message : 'Could not load reports.')
      }
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, isAuthChecked, navigate, load])

  function patchParams(mutate: (next: URLSearchParams) => void) {
    const next = new URLSearchParams(searchParams)
    mutate(next)
    setSearchParams(next, { replace: true })
  }

  function setParam(key: string, value: string | null) {
    patchParams((next) => (value === null ? next.delete(key) : next.set(key, value)))
  }

  function toggleId(key: string, id: number, current: number[]) {
    const nextIds = current.includes(id) ? current.filter((x) => x !== id) : [...current, id]
    setParam(key, nextIds.length > 0 ? nextIds.join(',') : null)
  }

  const label = (key: string) => bucketLabel(key, grain as Grain)

  const categoryRows = useMemo(
    () =>
      (report?.spending_by_category ?? [])
        .filter((row) => Number(row.total) > 0)
        .slice(0, 8)
        .map((row) => ({ label: row.category, value: Number(row.total) })),
    [report],
  )

  // Accounts grouped by institution for the filter list.
  const accountGroups = useMemo(() => {
    const groups: { name: string; accounts: Account[] }[] = []
    for (const inst of institutions) {
      const owned = accounts.filter((a) => a.plaid_item_id === inst.id)
      if (owned.length > 0) groups.push({ name: inst.institution_name, accounts: owned })
    }
    const rest = accounts.filter((a) => !institutions.some((i) => i.id === a.plaid_item_id))
    if (rest.length > 0) groups.push({ name: 'Not linked', accounts: rest })
    return groups
  }, [accounts, institutions])

  // Only top-level lines (groups + standalone categories) in the filter.
  const filterableCategories = useMemo(
    () => categories.filter((c) => c.parent_id === null && !c.archived),
    [categories],
  )

  if (!report) {
    return error ? (
      <AppShell>
        <p className="text-sm text-(--color-negative)">{error}</p>
      </AppShell>
    ) : (
      <PageLoading />
    )
  }

  const expenseSeries = report.income_vs_expense.map((m) => Number(m.expense))
  const incomeSeries = report.income_vs_expense.map((m) => Number(m.income))

  const selectClass =
    'rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-(--color-text) outline-none focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)'

  return (
    <AppShell>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold tracking-tight text-(--color-text)">Reports</h1>
        <div className="flex flex-wrap items-center gap-2 text-sm text-(--color-text-muted)">
          <label className="flex items-center gap-1.5">
            From
            <select value={from} onChange={(e) => setParam('from', e.target.value)} className={selectClass}>
              {MONTH_OPTIONS.map((m) => (
                <option key={m} value={m}>
                  {shortMonth(m)} {m.slice(0, 4)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            To
            <select value={to} onChange={(e) => setParam('to', e.target.value)} className={selectClass}>
              {MONTH_OPTIONS.map((m) => (
                <option key={m} value={m}>
                  {shortMonth(m)} {m.slice(0, 4)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {/* filter bar */}
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-(--color-border) bg-(--color-surface) p-3 text-sm">
        <div className="inline-flex overflow-hidden rounded-md border border-(--color-border)" role="group" aria-label="Period grain">
          {GRAINS.map((g) => (
            <button
              key={g}
              type="button"
              aria-pressed={grain === g}
              onClick={() => setParam('grain', g === 'month' ? null : g)}
              className={`px-2.5 py-1 capitalize transition-colors ${
                grain === g
                  ? 'bg-(--color-accent) text-(--color-on-accent)'
                  : 'text-(--color-text-muted) hover:bg-(--color-surface-hover)'
              }`}
            >
              {g}
            </button>
          ))}
        </div>

        <label className="flex items-center gap-1.5 text-(--color-text-muted)">
          <input
            type="checkbox"
            checked={excludeTransfers}
            onChange={(e) => setParam('transfers', e.target.checked ? null : 'include')}
          />
          Exclude transfers
        </label>

        <details className="relative">
          <summary className="cursor-pointer list-none rounded-md border border-(--color-border) px-2.5 py-1 text-(--color-text-muted) hover:bg-(--color-surface-hover)">
            Accounts{accountIds.length > 0 ? ` (${accountIds.length})` : ''}
          </summary>
          <div className="absolute right-0 z-10 mt-1 max-h-72 w-[min(14rem,calc(100vw-2rem))] overflow-y-auto rounded-md border border-(--color-border) bg-(--color-surface) p-2 shadow-lg sm:w-56">
            {accountGroups.length === 0 && <p className="px-1 text-xs text-(--color-text-faint)">No accounts</p>}
            {accountGroups.map((group) => (
              <div key={group.name} className="mb-1.5">
                <p className="px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-(--color-text-faint)">
                  {group.name}
                </p>
                {group.accounts.map((account) => (
                  <label key={account.id} className="flex items-center gap-1.5 px-1 py-0.5 text-(--color-text)">
                    <input
                      type="checkbox"
                      checked={accountIds.includes(account.id)}
                      onChange={() => toggleId('accounts', account.id, accountIds)}
                    />
                    {account.name}
                  </label>
                ))}
              </div>
            ))}
          </div>
        </details>

        <details className="relative">
          <summary className="cursor-pointer list-none rounded-md border border-(--color-border) px-2.5 py-1 text-(--color-text-muted) hover:bg-(--color-surface-hover)">
            Categories{categoryIds.length > 0 ? ` (${categoryIds.length})` : ''}
          </summary>
          <div className="absolute right-0 z-10 mt-1 max-h-72 w-[min(14rem,calc(100vw-2rem))] overflow-y-auto rounded-md border border-(--color-border) bg-(--color-surface) p-2 shadow-lg sm:w-56">
            {filterableCategories.length === 0 && (
              <p className="px-1 text-xs text-(--color-text-faint)">No categories</p>
            )}
            {filterableCategories.map((category) => (
              <label key={category.id} className="flex items-center gap-1.5 px-1 py-0.5 text-(--color-text)">
                <input
                  type="checkbox"
                  checked={categoryIds.includes(category.id)}
                  onChange={() => toggleId('categories', category.id, categoryIds)}
                />
                {category.name}
                {category.is_group && <span className="text-[10px] text-(--color-text-faint)">group</span>}
              </label>
            ))}
          </div>
        </details>

        {(accountIds.length > 0 || categoryIds.length > 0 || grain !== 'month' || !excludeTransfers) && (
          <button
            type="button"
            onClick={() =>
              setSearchParams(
                (() => {
                  const next = new URLSearchParams(searchParams)
                  for (const key of ['accounts', 'categories', 'grain', 'transfers']) next.delete(key)
                  return next
                })(),
                { replace: true },
              )
            }
            className="text-xs text-(--color-text-faint) underline hover:text-(--color-text-muted)"
          >
            Reset filters
          </button>
        )}
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded-md border border-(--color-negative)/30 bg-(--color-negative)/10 px-3 py-2 text-sm text-(--color-negative)">
          {error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Spending by period">
          <MonthBars
            months={report.buckets}
            formatLabel={label}
            series={[{ label: 'Spent', values: expenseSeries, tone: 'negative' }]}
          />
        </Panel>

        <Panel title="Income vs. expense">
          <MonthBars
            months={report.buckets}
            formatLabel={label}
            series={[
              { label: 'Income', values: incomeSeries, tone: 'accent' },
              { label: 'Expense', values: expenseSeries, tone: 'negative' },
            ]}
          />
        </Panel>

        <Panel title="Period over period">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[22rem] text-sm">
              <tbody className="divide-y divide-(--color-border)">
              {report.month_over_month_spend.map((row) => (
                <tr key={row.bucket}>
                  <td className="py-1.5 text-(--color-text-muted)">{label(row.bucket)}</td>
                  <td className="tabular-nums py-1.5 text-right text-(--color-text)">{formatMoney(Number(row.total))}</td>
                  <td
                    className={`tabular-nums py-1.5 pl-3 text-right ${
                      row.change === null
                        ? 'text-(--color-text-faint)'
                        : Number(row.change) > 0
                          ? 'text-(--color-negative)'
                          : 'text-(--color-accent)'
                    }`}
                  >
                    {row.change === null
                      ? '—'
                      : `${Number(row.change) > 0 ? '+' : ''}${formatMoney(Number(row.change))}`}
                    {row.change_pct !== null && (
                      <span className="ml-1 text-xs">({(Number(row.change_pct) * 100).toFixed(1)}%)</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </Panel>

        <Panel title="Top categories">
          <HBarList rows={categoryRows} />
        </Panel>

        <Panel title="Top merchants">
          <HBarList
            rows={report.top_merchants.map((m) => ({
              label: m.description,
              value: Number(m.total),
              sublabel: `${m.count}×`,
            }))}
          />
        </Panel>
      </div>
    </AppShell>
  )
}
