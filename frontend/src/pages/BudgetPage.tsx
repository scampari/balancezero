import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  type Budget,
  type CategoryPatch,
  type TargetType,
  createCategoryWithAutoRefresh,
  getBudgetWithAutoRefresh,
  patchCategoryWithAutoRefresh,
  setAllocationWithAutoRefresh,
  setCategoryTargetWithAutoRefresh,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AppShell, PageLoading } from '../components/AppShell'

type Category = Budget['categories'][number]

function formatMoney(value: string): string {
  return Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

const CURRENT_MONTH = new Date().toISOString().slice(0, 7) + '-01'

const COLLAPSED_KEY = 'bz.budget.collapsed'

function readCollapsed(): Set<number> {
  try {
    const raw = window.localStorage.getItem(COLLAPSED_KEY)
    return new Set(raw ? (JSON.parse(raw) as number[]) : [])
  } catch {
    return new Set()
  }
}

function writeCollapsed(ids: Set<number>): void {
  try {
    window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...ids]))
  } catch {
    // non-fatal — collapse state just won't persist this session
  }
}

const NUM_CELL = 'w-28 shrink-0 text-right tabular-nums text-sm'
const HEAD_CELL = 'w-28 shrink-0 text-right text-xs font-medium tracking-wide text-(--color-text-muted) uppercase'
const MINI_BTN =
  'rounded px-1.5 py-0.5 text-xs text-(--color-text-faint) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text-muted) disabled:cursor-not-allowed disabled:opacity-40'

export function BudgetPage() {
  const { accessToken, setAccessToken, isAuthChecked } = useAuth()
  const navigate = useNavigate()
  const [budget, setBudget] = useState<Budget | null>(null)
  const [newCategoryName, setNewCategoryName] = useState('')
  const [newCategoryParent, setNewCategoryParent] = useState('')
  const [isCreatingCategory, setIsCreatingCategory] = useState(false)
  const [categoryError, setCategoryError] = useState<string | null>(null)
  const [manageError, setManageError] = useState<string | null>(null)
  const [allocationDrafts, setAllocationDrafts] = useState<Record<number, string>>({})
  const [renamingId, setRenamingId] = useState<number | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [targetEditorFor, setTargetEditorFor] = useState<number | null>(null)
  const [targetType, setTargetType] = useState<TargetType>('monthly')
  const [targetAmount, setTargetAmount] = useState('')
  const [targetDate, setTargetDate] = useState('')
  const [targetError, setTargetError] = useState<string | null>(null)
  const [isSavingTarget, setIsSavingTarget] = useState(false)
  const [collapsed, setCollapsed] = useState<Set<number>>(readCollapsed)

  function toggleCollapse(categoryId: number) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(categoryId)) next.delete(categoryId)
      else next.add(categoryId)
      writeCollapsed(next)
      return next
    })
  }

  function loadBudget(token: string) {
    return getBudgetWithAutoRefresh(token, setAccessToken).then((data) => setBudget(data))
  }

  async function applyPatch(categoryId: number, patch: CategoryPatch) {
    if (!accessToken) return
    setManageError(null)
    try {
      await patchCategoryWithAutoRefresh(accessToken, setAccessToken, categoryId, patch)
      await loadBudget(accessToken)
    } catch (err) {
      setManageError(err instanceof Error ? err.message : 'Could not update category.')
    }
  }

  function openTargetEditor(category: Category) {
    setTargetEditorFor(category.id)
    setTargetError(null)
    setTargetType(category.target?.target_type ?? 'monthly')
    setTargetAmount(category.target?.target_amount ?? '')
    setTargetDate(category.target?.target_date ?? '')
  }

  async function handleSaveTarget(categoryId: number) {
    if (!accessToken) return
    setTargetError(null)
    setIsSavingTarget(true)
    try {
      await setCategoryTargetWithAutoRefresh(accessToken, setAccessToken, categoryId, {
        target_type: targetType,
        target_amount: targetAmount.trim(),
        ...(targetType === 'custom' ? { target_date: targetDate } : {}),
      })
      setTargetEditorFor(null)
      await loadBudget(accessToken)
    } catch (err) {
      setTargetError(err instanceof Error ? err.message : 'Could not save target.')
    } finally {
      setIsSavingTarget(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    if (!isAuthChecked) return
    if (!accessToken) {
      navigate('/login', { replace: true })
      return
    }
    loadBudget(accessToken).catch(() => {
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

  async function handleCreateCategory(event: FormEvent) {
    event.preventDefault()
    if (!accessToken || !newCategoryName.trim()) return
    setCategoryError(null)
    setIsCreatingCategory(true)
    try {
      await createCategoryWithAutoRefresh(
        accessToken,
        setAccessToken,
        newCategoryName.trim(),
        newCategoryParent === '' ? null : Number(newCategoryParent),
      )
      setNewCategoryName('')
      setNewCategoryParent('')
      await loadBudget(accessToken)
    } catch (err) {
      setCategoryError(err instanceof Error ? err.message : 'Could not create category.')
    } finally {
      setIsCreatingCategory(false)
    }
  }

  async function handleAllocationCommit(categoryId: number) {
    const draft = allocationDrafts[categoryId]
    if (!accessToken || draft === undefined) return
    setAllocationDrafts((prev) => {
      const next = { ...prev }
      delete next[categoryId]
      return next
    })
    if (draft === '' || Number.isNaN(Number(draft))) return
    await setAllocationWithAutoRefresh(accessToken, setAccessToken, categoryId, CURRENT_MONTH, draft)
    await loadBudget(accessToken)
  }

  function commitRename(categoryId: number) {
    const name = renameDraft.trim()
    setRenamingId(null)
    const current = budget?.categories.find((c) => c.id === categoryId)?.name
    if (!name || name === current) return
    applyPatch(categoryId, { name })
  }

  if (!budget) return <PageLoading />

  const readyToAssign = Number(budget.ready_to_assign)
  const topLevel = budget.categories.filter((c) => c.parent_id == null)
  const childrenOf = (parentId: number) => budget.categories.filter((c) => c.parent_id === parentId)
  const orphans = budget.categories.filter(
    (c) => c.parent_id != null && !budget.categories.some((p) => p.id === c.parent_id),
  )
  // The auto-managed "Credit Card Payments" group holds only payment
  // envelopes — you can't file a category or a transaction under it.
  const isPaymentGroup = (c: Category) =>
    budget.categories.some((k) => k.parent_id === c.id && k.is_payment_category)
  const parentChoices = topLevel.filter((c) => !isPaymentGroup(c))
  const moveTargets = parentChoices // a category can only be re-parented under a top-level one

  function paymentLine(category: Category) {
    const available = Number(category.available)
    return (
      <div className="flex flex-1 flex-col gap-0.5 text-xs">
        <span className="text-(--color-text-faint)">
          Card: {formatMoney(category.card_spending_this_month ?? '0')} spent this month ·{' '}
          {formatMoney(category.card_payments_this_month ?? '0')} paid
        </span>
        <span className={available < 0 ? 'text-(--color-negative)' : 'text-(--color-text-faint)'}>
          {formatMoney(category.available)} available to pay
          {available < 0 && ' — debt not covered by your budget'}
        </span>
      </div>
    )
  }

  function targetLine(category: Category) {
    const t = category.target
    if (!t) return null
    if (t.target_type === 'monthly') {
      return (
        <span className="text-xs text-(--color-text-faint)">
          {formatMoney(t.funded)} of {formatMoney(t.target_amount)} this month
        </span>
      )
    }
    const pct = Math.round(Number(t.progress) * 100)
    const horizon = t.target_type === 'yearly' ? 'by year-end' : `by ${t.target_date}`
    return (
      <div className="flex flex-1 flex-col gap-1">
        <span className="text-xs text-(--color-text-faint)">
          {Number(t.needed_this_month) > 0
            ? `Assign ${formatMoney(t.needed_this_month)} more this month`
            : 'On track — nothing needed this month'}
          {' · '}
          {formatMoney(t.funded)} of {formatMoney(t.target_amount)} {horizon}
        </span>
        <div className="h-1 w-full max-w-64 overflow-hidden rounded-full bg-(--color-border)">
          <div
            className="h-full rounded-full bg-(--color-accent)"
            style={{ width: `${Math.min(100, pct)}%` }}
          />
        </div>
      </div>
    )
  }

  function renderCategoryRow(category: Category, isChild: boolean, siblings: Category[]) {
    const available = Number(category.available)
    const draft = allocationDrafts[category.id]
    const idx = siblings.findIndex((c) => c.id === category.id)
    const isPayment = category.is_payment_category
    return (
      <li
        key={category.id}
        data-category={category.name}
        className={`flex flex-col gap-2 bg-(--color-surface) py-3 pr-4 transition-colors hover:bg-(--color-surface-hover) ${
          isChild ? 'pl-10' : 'pl-4'
        }`}
      >
        <div className="flex items-center gap-4">
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            {category.is_group && (
              <button
                type="button"
                aria-label={`${collapsed.has(category.id) ? 'Expand' : 'Collapse'} ${category.name}`}
                onClick={() => toggleCollapse(category.id)}
                className="shrink-0 text-xs text-(--color-text-faint) transition-colors hover:text-(--color-text)"
              >
                {collapsed.has(category.id) ? '▸' : '▾'}
              </button>
            )}
            {isChild && <span className="text-(--color-text-faint)">↳</span>}
            {renamingId === category.id ? (
              <input
                autoFocus
                aria-label={`Rename ${category.name}`}
                value={renameDraft}
                onChange={(e) => setRenameDraft(e.target.value)}
                onBlur={() => commitRename(category.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') e.currentTarget.blur()
                  if (e.key === 'Escape') setRenamingId(null)
                }}
                className="min-w-0 flex-1 rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-0.5 text-sm text-(--color-text) outline-none focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
              />
            ) : (
              <span
                className={`truncate text-sm ${
                  isChild
                    ? 'text-(--color-text-muted)'
                    : category.is_group
                      ? 'font-medium text-(--color-text)'
                      : 'text-(--color-text)'
                }`}
              >
                {category.name}
              </span>
            )}
          </div>
          <span
            className={`${NUM_CELL} ${
              Number(category.spent_this_month) < 0 ? 'text-(--color-text)' : 'text-(--color-text-faint)'
            }`}
          >
            {formatMoney(category.spent_this_month)}
          </span>
          <span
            className={`${NUM_CELL} font-medium ${
              available < 0 ? 'text-(--color-negative)' : 'text-(--color-text)'
            }`}
          >
            {formatMoney(category.available)}
          </span>
          {category.is_group ? (
            <span className={`${NUM_CELL} font-medium text-(--color-text-muted)`}>
              {formatMoney(category.allocated_this_month)}
            </span>
          ) : (
            <label className="flex w-28 shrink-0 items-center justify-end gap-1.5">
              <span className="text-xs text-(--color-text-faint)">$</span>
              <input
                type="text"
                inputMode="decimal"
                aria-label={`Assign amount for ${category.name}`}
                value={draft ?? category.allocated_this_month}
                onChange={(event) =>
                  setAllocationDrafts((prev) => ({ ...prev, [category.id]: event.target.value }))
                }
                onBlur={() => handleAllocationCommit(category.id)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') event.currentTarget.blur()
                }}
                className="tabular-nums w-20 rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-right text-xs text-(--color-text) outline-none transition-colors focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
              />
            </label>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          {isPayment ? paymentLine(category) : targetLine(category)}
          <div className="ml-auto flex items-center gap-1.5">
            {!category.is_group && !isPayment && (
              <button
                type="button"
                onClick={() =>
                  targetEditorFor === category.id ? setTargetEditorFor(null) : openTargetEditor(category)
                }
                className={MINI_BTN}
              >
                {category.target ? 'Edit target' : 'Set target'}
              </button>
            )}
            {!isPayment && (
              <>
                <button
                  type="button"
                  onClick={() => {
                    setRenameDraft(category.name)
                    setRenamingId(category.id)
                  }}
                  className={MINI_BTN}
                >
                  Rename
                </button>
                <select
                  aria-label={`Move ${category.name}`}
                  value={category.parent_id ?? ''}
                  onChange={(e) =>
                    applyPatch(category.id, { parent_id: e.target.value === '' ? null : Number(e.target.value) })
                  }
                  className={`${MINI_BTN} appearance-none pr-1`}
                >
                  <option value="">Top level</option>
                  {moveTargets
                    .filter((p) => p.id !== category.id)
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        Under {p.name}
                      </option>
                    ))}
                </select>
              </>
            )}
            <button
              type="button"
              aria-label={`Move ${category.name} up`}
              disabled={idx <= 0}
              onClick={() => applyPatch(category.id, { position: idx - 1 })}
              className={MINI_BTN}
            >
              ↑
            </button>
            <button
              type="button"
              aria-label={`Move ${category.name} down`}
              disabled={idx < 0 || idx >= siblings.length - 1}
              onClick={() => applyPatch(category.id, { position: idx + 1 })}
              className={MINI_BTN}
            >
              ↓
            </button>
            {!isPayment && (
              <button
                type="button"
                onClick={() => applyPatch(category.id, { archived: true })}
                className={MINI_BTN}
              >
                Archive
              </button>
            )}
          </div>
        </div>

        {targetEditorFor === category.id && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-(--color-border) bg-(--color-bg) p-2">
            <select
              aria-label="Target type"
              value={targetType}
              onChange={(event) => setTargetType(event.target.value as TargetType)}
              className="rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-xs text-(--color-text) outline-none focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
            >
              <option value="monthly">Monthly</option>
              <option value="yearly">Yearly</option>
              <option value="custom">By date</option>
            </select>
            <label className="flex items-center gap-1.5">
              <span className="text-xs text-(--color-text-faint)">$</span>
              <input
                type="text"
                inputMode="decimal"
                aria-label="Target amount"
                value={targetAmount}
                onChange={(event) => setTargetAmount(event.target.value)}
                className="tabular-nums w-24 rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-right text-xs text-(--color-text) outline-none focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
              />
            </label>
            {targetType === 'custom' && (
              <input
                type="date"
                aria-label="Target date"
                value={targetDate}
                onChange={(event) => setTargetDate(event.target.value)}
                className="rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-xs text-(--color-text) outline-none focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
              />
            )}
            <button
              type="button"
              onClick={() => handleSaveTarget(category.id)}
              disabled={isSavingTarget || !targetAmount.trim()}
              className="rounded-md bg-(--color-accent) px-3 py-1 text-xs font-medium text-(--color-on-accent) transition-colors hover:bg-(--color-accent-hover) disabled:cursor-not-allowed disabled:opacity-60"
            >
              Save
            </button>
            {targetError && (
              <span role="alert" className="text-xs text-(--color-negative)">
                {targetError}
              </span>
            )}
          </div>
        )}
      </li>
    )
  }

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

      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-(--color-text-muted)">Categories</h2>
      </div>

      <div className="overflow-hidden rounded-xl border border-(--color-border)">
        {budget.categories.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-(--color-text-faint)">No categories yet.</p>
        ) : (
          <>
            <div className="flex items-center gap-4 border-b border-(--color-border) bg-(--color-surface) px-4 py-2">
              <span className="flex-1 text-xs font-medium tracking-wide text-(--color-text-muted) uppercase">
                Category
              </span>
              <span className={HEAD_CELL}>Spent</span>
              <span className={HEAD_CELL}>Available to Spend</span>
              <span className={HEAD_CELL}>Budgeted</span>
            </div>
            <ul className="divide-y divide-(--color-border)">
              {topLevel.map((parent) => {
                const kids = childrenOf(parent.id)
                const hideKids = parent.is_group && collapsed.has(parent.id)
                return [
                  renderCategoryRow(parent, false, topLevel),
                  ...(hideKids ? [] : kids.map((child) => renderCategoryRow(child, true, kids))),
                ]
              })}
              {orphans.map((orphan) => renderCategoryRow(orphan, true, orphans))}
            </ul>
            <div
              data-testid="budget-totals"
              className="flex items-center gap-4 border-t-2 border-(--color-border) bg-(--color-surface) px-4 py-2.5"
            >
              <span className="flex-1 text-xs font-semibold tracking-wide text-(--color-text-muted) uppercase">
                Total
              </span>
              <span className={`${NUM_CELL} font-semibold text-(--color-text)`}>
                {formatMoney(budget.totals.spent)}
              </span>
              <span className={`${NUM_CELL} font-semibold text-(--color-text)`}>
                {formatMoney(budget.totals.available)}
              </span>
              <span className="flex w-28 shrink-0 items-center justify-end pr-2">
                <span className="tabular-nums text-sm font-semibold text-(--color-text)">
                  {formatMoney(budget.totals.budgeted)}
                </span>
              </span>
            </div>
          </>
        )}

        <form
          onSubmit={handleCreateCategory}
          className="flex flex-wrap items-center gap-2 border-t border-(--color-border) bg-(--color-surface) px-4 py-3"
        >
          <input
            type="text"
            value={newCategoryName}
            onChange={(event) => setNewCategoryName(event.target.value)}
            placeholder="New category name"
            className="flex-1 rounded-md border border-(--color-border) bg-(--color-bg) px-2.5 py-1.5 text-sm text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-faint) focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
          />
          <select
            aria-label="Parent category"
            value={newCategoryParent}
            onChange={(event) => setNewCategoryParent(event.target.value)}
            className="rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1.5 text-sm text-(--color-text) outline-none transition-colors focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
          >
            <option value="">Top-level category</option>
            {parentChoices.map((parent) => (
              <option key={parent.id} value={parent.id}>
                Subcategory of {parent.name}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={isCreatingCategory || !newCategoryName.trim()}
            className="rounded-md bg-(--color-accent) px-3 py-1.5 text-sm font-medium text-(--color-on-accent) transition-colors hover:bg-(--color-accent-hover) disabled:cursor-not-allowed disabled:opacity-60"
          >
            Add
          </button>
        </form>
      </div>

      {manageError && (
        <p role="alert" className="mt-2 text-sm text-(--color-negative)">
          {manageError}
        </p>
      )}
      {categoryError && (
        <p role="alert" className="mt-2 text-sm text-(--color-negative)">
          {categoryError}
        </p>
      )}

      {budget.archived_categories.length > 0 && (
        <details className="mt-6 overflow-hidden rounded-xl border border-(--color-border)">
          <summary className="cursor-pointer bg-(--color-surface) px-4 py-2.5 text-xs font-medium tracking-wide text-(--color-text-muted) uppercase">
            Archived ({budget.archived_categories.length})
          </summary>
          <ul className="divide-y divide-(--color-border)">
            {budget.archived_categories.map((category) => (
              <li
                key={category.id}
                data-archived-category={category.name}
                className="flex items-center gap-4 bg-(--color-surface) px-4 py-3"
              >
                <span className="flex-1 truncate text-sm text-(--color-text-muted)">
                  {category.name}
                </span>
                <span className={`${NUM_CELL} text-(--color-text-faint)`}>
                  {formatMoney(category.available)}
                </span>
                <button
                  type="button"
                  onClick={() => applyPatch(category.id, { archived: false })}
                  className={MINI_BTN}
                >
                  Unarchive
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </AppShell>
  )
}
