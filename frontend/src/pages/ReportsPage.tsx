import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { type ReportsResponse, getReportsWithAutoRefresh } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AppShell, PageLoading } from '../components/AppShell'
import { HBarList } from '../components/charts/HBarList'
import { MonthBars } from '../components/charts/MonthBars'
import { formatMoney, shortMonth } from '../components/charts/chartScale'

function monthKey(offsetFromNow: number): string {
  const now = new Date()
  const d = new Date(now.getFullYear(), now.getMonth() - offsetFromNow, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

// Last 18 months, newest first — enough for the pickers without hitting the
// backend's 24-month cap.
const MONTH_OPTIONS = Array.from({ length: 18 }, (_, i) => monthKey(i))

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-(--color-border) bg-(--color-surface) p-4">
      <h2 className="mb-3 text-sm font-medium text-(--color-text-muted)">{title}</h2>
      {children}
    </section>
  )
}

export function ReportsPage() {
  const { accessToken, setAccessToken, isAuthChecked } = useAuth()
  const navigate = useNavigate()
  const [from, setFrom] = useState(() => monthKey(5))
  const [to, setTo] = useState(() => monthKey(0))
  const [report, setReport] = useState<ReportsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    (token: string, fromValue: string, toValue: string) =>
      getReportsWithAutoRefresh(token, setAccessToken, fromValue, toValue).then(setReport),
    [setAccessToken],
  )

  useEffect(() => {
    let cancelled = false
    if (!isAuthChecked) return
    if (!accessToken) {
      navigate('/login', { replace: true })
      return
    }
    setError(null)
    load(accessToken, from, to).catch((err) => {
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
  }, [accessToken, isAuthChecked, navigate, from, to])

  const categoryRows = useMemo(
    () =>
      (report?.spending_by_category ?? [])
        .filter((row) => Number(row.total) > 0)
        .slice(0, 8)
        .map((row) => ({ label: row.category, value: Number(row.total) })),
    [report],
  )

  if (!report) return error ? <AppShell><p className="text-sm text-(--color-negative)">{error}</p></AppShell> : <PageLoading />

  const expenseSeries = report.income_vs_expense.map((m) => Number(m.expense))
  const incomeSeries = report.income_vs_expense.map((m) => Number(m.income))

  return (
    <AppShell>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold tracking-tight text-(--color-text)">Reports</h1>
        <div className="flex items-center gap-2 text-sm text-(--color-text-muted)">
          <label className="flex items-center gap-1.5">
            From
            <select
              value={from}
              onChange={(event) => setFrom(event.target.value)}
              className="rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-(--color-text) outline-none focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
            >
              {MONTH_OPTIONS.map((m) => (
                <option key={m} value={m}>{shortMonth(m)} {m.slice(0, 4)}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            To
            <select
              value={to}
              onChange={(event) => setTo(event.target.value)}
              className="rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-(--color-text) outline-none focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
            >
              {MONTH_OPTIONS.map((m) => (
                <option key={m} value={m}>{shortMonth(m)} {m.slice(0, 4)}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded-md border border-(--color-negative)/30 bg-(--color-negative)/10 px-3 py-2 text-sm text-(--color-negative)">
          {error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Spending by month">
          <MonthBars
            months={report.months}
            series={[{ label: 'Spent', values: expenseSeries, tone: 'negative' }]}
          />
        </Panel>

        <Panel title="Income vs. expense">
          <MonthBars
            months={report.months}
            series={[
              { label: 'Income', values: incomeSeries, tone: 'accent' },
              { label: 'Expense', values: expenseSeries, tone: 'negative' },
            ]}
          />
        </Panel>

        <Panel title="Month over month">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-(--color-border)">
              {report.month_over_month_spend.map((row) => (
                <tr key={row.month}>
                  <td className="py-1.5 text-(--color-text-muted)">{shortMonth(row.month)} {row.month.slice(0, 4)}</td>
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
