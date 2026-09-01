import { useEffect, useState, type SyntheticEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
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
import { localMonthKey } from '../lib/dates'

type Category = Budget['categories'][number]

function formatMoney(value: string): string {
  return Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

// Zero-based budgeting lives or dies by the "available" column, so it's the
// one that's color-coded: money left to spend (accent), overspent
// (negative), or spent to the dollar (faint).
function availableColor(value: number): string {
  if (value < 0) return 'text-(--color-negative)'
  if (value === 0) return 'text-(--color-text-faint)'
  return 'text-(--color-accent)'
}

// The budget is separated by month (changes/025). The viewed month is a
// "YYYY-MM" key held in the URL (?month=), absent for the current month.
// "current" is the viewer's *local* month, not UTC (changes/027).
function currentMonthKey(): string {
  return localMonthKey()
}

function shiftMonth(key: string, delta: number): string {
  const [year, month] = key.split('-').map(Number)
  const d = new Date(year, month - 1 + delta, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function monthLabel(key: string): string {
  const [year, month] = key.split('-').map(Number)
  return new Date(year, month - 1, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
}

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

// Full-width in the mobile stat grid; fixed column on desktop (>= sm).
// Centered so each figure sits directly under its header.
const NUM_CELL = 'w-full text-center tabular-nums text-sm sm:w-28 sm:shrink-0'
const HEAD_CELL = 'w-28 shrink-0 text-center text-xs font-medium tracking-wide text-(--color-text-muted) uppercase'
const STAT_LABEL = 'text-center text-[10px] font-medium tracking-wide text-(--color-text-faint) uppercase sm:hidden'
const MINI_BTN =
  'rounded px-1.5 py-0.5 text-xs text-(--color-text-faint) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text-muted) disabled:cursor-not-allowed disabled:opacity-40'
// A pill inside a category row's expanded ⋮ actions panel.
const MENU_ITEM =
  'rounded border border-(--color-border) bg-(--color-surface) px-2 py-1 text-xs text-(--color-text-muted) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text) disabled:cursor-not-allowed disabled:opacity-40'

// The ⋮ menu is a plain <details>; collapse it after an action fires.
function closeRowMenu(event: SyntheticEvent): void {
  event.currentTarget.closest('details')?.removeAttribute('open')
}

// The category row's <summary> spans the whole row, so clicks on its
// interactive bits (name, rename/assign inputs, collapse caret) would also
// toggle the actions panel. Swallow the summary's default toggle for those;
// only a click on the ⋮ itself opens the panel.
function noToggle(event: SyntheticEvent): void {
  event.preventDefault()
}

const KEBAB_BASE =
  'h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded text-base leading-none text-(--color-text-faint) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text) group-open:bg-(--color-surface-hover) group-open:text-(--color-text)'

export function BudgetPage() {
  const { accessToken, setAccessToken, isAuthChecked } = useAuth()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const month = searchParams.get('month') ?? currentMonthKey()
  const monthDate = `${month}-01`
  const [budget, setBudget] = useState<Budget | null>(null)

  function goToMonth(nextKey: string) {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (nextKey === currentMonthKey()) next.delete('month')
        else next.set('month', nextKey)
        return next
      },
      { replace: true },
    )
  }
  // false = not adding; null = adding a top-level category; number = adding a
  // subcategory under that parent id.
  const [addingUnder, setAddingUnder] = useState<number | null | false>(false)
  const [newCatDraft, setNewCatDraft] = useState('')
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

  function loadBudget(token: string, forMonth: string = monthDate) {
    return getBudgetWithAutoRefresh(token, setAccessToken, forMonth).then((data) => setBudget(data))
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
  }, [accessToken, isAuthChecked, navigate, setAccessToken, monthDate])

  function openNewCategory(parentId: number | null) {
    setNewCatDraft('')
    setCategoryError(null)
    setAddingUnder(parentId)
  }

  function cancelNewCategory() {
    setNewCatDraft('')
    setCategoryError(null)
    setAddingUnder(false)
  }

  async function submitNewCategory(parentId: number | null) {
    const name = newCatDraft.trim()
    if (!accessToken || !name) return
    setCategoryError(null)
    setIsCreatingCategory(true)
    try {
      await createCategoryWithAutoRefresh(accessToken, setAccessToken, name, parentId)
      setNewCatDraft('')
      setAddingUnder(false)
      await loadBudget(accessToken)
    } catch (err) {
      setCategoryError(err instanceof Error ? err.message : 'Could not create category.')
    } finally {
      setIsCreatingCategory(false)
    }
  }

  function renderNewCategoryRow(parentId: number | null) {
    const isChild = parentId != null
    return (
      <li key={`new-${parentId ?? 'root'}`} className="bg-(--color-surface) py-2 pr-4 pl-4">
        <input
          autoFocus
          aria-label={isChild ? 'New subcategory name' : 'New category name'}
          placeholder={isChild ? 'New subcategory…' : 'New category…'}
          value={newCatDraft}
          disabled={isCreatingCategory}
          onChange={(e) => setNewCatDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              void submitNewCategory(parentId)
            }
            if (e.key === 'Escape') cancelNewCategory()
          }}
          onBlur={() => {
            if (!newCatDraft.trim()) cancelNewCategory()
          }}
          className="w-full rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-sm text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-faint) focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
        />
        {categoryError && (
          <p role="alert" className="mt-1 text-xs text-(--color-negative)">
            {categoryError}
          </p>
        )}
      </li>
    )
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
    await setAllocationWithAutoRefresh(accessToken, setAccessToken, categoryId, monthDate, draft)
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

  // The month-to-month carry (changes/025): what this envelope started the
  // viewed month with, before this month's own assignments and spending.
  function rolloverLine(category: Category) {
    const rollover = Number(category.rollover)
    if (rollover === 0) return null
    return (
      <span
        className={`text-xs ${rollover < 0 ? 'text-(--color-negative)' : 'text-(--color-text-faint)'}`}
      >
        {rollover < 0
          ? `Overspent last month ${formatMoney(category.rollover)}`
          : `Rolled over +${formatMoney(category.rollover)}`}
      </span>
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
        className="flex flex-col gap-1 bg-(--color-surface) px-4 py-3 transition-colors hover:bg-(--color-surface-hover)"
      >
        {/* The whole row is the <summary>: name + centered stats + a ⋮ that
            reveals the actions panel. Clicks on the name / inputs are
            swallowed by noToggle so only the ⋮ opens the panel. */}
        <details className="group">
          <summary className="flex list-none flex-col gap-1 [&::-webkit-details-marker]:hidden">
           <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
            <div className="flex min-w-0 items-center gap-1.5 sm:flex-1">
              <div className="flex min-w-0 flex-1 items-center gap-1.5" onClick={noToggle}>
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
                {parentChoices.some((p) => p.id === category.id) && (
                  <button
                    type="button"
                    aria-label={`Add subcategory under ${category.name}`}
                    onClick={() => openNewCategory(category.id)}
                    className="shrink-0 rounded px-1 text-base leading-none text-(--color-text-faint) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text)"
                  >
                    +
                  </button>
                )}
              </div>
              {/* mobile: ⋮ rides the name row, top-right of the card */}
              <span aria-hidden className={`${KEBAB_BASE} flex sm:hidden`}>⋮</span>
            </div>

            {/* Stats: a labeled 3-up grid on mobile; three fixed centered
                columns on desktop (wrappers collapse via display:contents). */}
            <div className="grid grid-cols-3 gap-2 sm:contents" onClick={noToggle}>
              <div className="flex flex-col gap-0.5 sm:contents">
                <span className={STAT_LABEL}>Spent</span>
                <span
                  className={`${NUM_CELL} ${
                    Number(category.spent_this_month) < 0 ? 'text-(--color-text)' : 'text-(--color-text-faint)'
                  }`}
                >
                  {formatMoney(category.spent_this_month)}
                </span>
              </div>
              <div className="flex flex-col gap-0.5 sm:contents">
                <span className={STAT_LABEL}>Available</span>
                <span className={`${NUM_CELL} font-medium ${availableColor(available)}`}>
                  {formatMoney(category.available)}
                </span>
              </div>
              <div className="flex flex-col gap-0.5 sm:contents">
                <span className={STAT_LABEL}>{category.is_group ? 'Budgeted' : 'Assign'}</span>
                {category.is_group ? (
                  <span className={`${NUM_CELL} font-medium text-(--color-text-muted)`}>
                    {formatMoney(category.allocated_this_month)}
                  </span>
                ) : (
                  <label className="flex items-center justify-center gap-1.5 sm:w-28 sm:shrink-0">
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
                      className="tabular-nums w-full min-w-0 rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-center text-xs text-(--color-text) outline-none transition-colors focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg) sm:w-20"
                    />
                  </label>
                )}
              </div>
            </div>

            {/* desktop: ⋮ centered at the right of the row */}
            <span aria-hidden className={`${KEBAB_BASE} hidden shrink-0 sm:flex`}>⋮</span>
           </div>

            {/* meta line stays visible at rest (target progress / card
                payment status); only the actions below it are disclosed */}
            {(isPayment || category.target || Number(category.rollover) !== 0) && (
              <div className="flex min-w-0 flex-col gap-0.5" onClick={noToggle}>
                {isPayment ? (
                  paymentLine(category)
                ) : (
                  <>
                    {rolloverLine(category)}
                    {targetLine(category)}
                  </>
                )}
              </div>
            )}
          </summary>

          <div className="mt-1.5 flex flex-wrap items-center gap-1 rounded-md border border-(--color-border) bg-(--color-bg) p-1.5">
            {!category.is_group && !isPayment && (
              <button
                type="button"
                onClick={(e) => {
                  closeRowMenu(e)
                  if (targetEditorFor === category.id) setTargetEditorFor(null)
                  else openTargetEditor(category)
                }}
                className={MENU_ITEM}
              >
                {category.target ? 'Edit target' : 'Set target'}
              </button>
            )}
            {!isPayment && (
              <button
                type="button"
                onClick={(e) => {
                  closeRowMenu(e)
                  setRenameDraft(category.name)
                  setRenamingId(category.id)
                }}
                className={MENU_ITEM}
              >
                Rename
              </button>
            )}
            <button
              type="button"
              disabled={idx <= 0}
              onClick={(e) => {
                closeRowMenu(e)
                applyPatch(category.id, { position: idx - 1 })
              }}
              className={MENU_ITEM}
            >
              Move up
            </button>
            <button
              type="button"
              disabled={idx < 0 || idx >= siblings.length - 1}
              onClick={(e) => {
                closeRowMenu(e)
                applyPatch(category.id, { position: idx + 1 })
              }}
              className={MENU_ITEM}
            >
              Move down
            </button>
            {!isPayment && (
              <label className="flex items-center gap-1 text-[10px] font-medium tracking-wide text-(--color-text-faint) uppercase">
                <span className="sr-only sm:not-sr-only">Move to</span>
                <select
                  aria-label={`Move ${category.name}`}
                  value={category.parent_id ?? ''}
                  onChange={(e) => {
                    closeRowMenu(e)
                    applyPatch(category.id, {
                      parent_id: e.target.value === '' ? null : Number(e.target.value),
                    })
                  }}
                  className="rounded border border-(--color-border) bg-(--color-bg) px-1.5 py-1 text-xs font-normal normal-case text-(--color-text) outline-none focus:border-(--color-accent-border) focus:ring-2 focus:ring-(--color-accent-bg)"
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
              </label>
            )}
            {!isPayment && (
              <button
                type="button"
                onClick={(e) => {
                  closeRowMenu(e)
                  applyPatch(category.id, { archived: true })
                }}
                className={`${MENU_ITEM} hover:text-(--color-negative)`}
              >
                Archive
              </button>
            )}
          </div>
        </details>

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
            <button
              type="button"
              onClick={() => setTargetEditorFor(null)}
              className="rounded-md px-2 py-1 text-xs text-(--color-text-faint) transition-colors hover:text-(--color-text-muted)"
            >
              Cancel
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
      <div className="mb-4 flex items-center justify-center gap-2">
        <button
          type="button"
          aria-label="Previous month"
          onClick={() => goToMonth(shiftMonth(month, -1))}
          className="rounded-md border border-(--color-border) px-2.5 py-1 text-sm text-(--color-text-muted) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text)"
        >
          ◂
        </button>
        <span className="min-w-40 text-center text-sm font-medium text-(--color-text)">
          {monthLabel(month)}
        </span>
        <button
          type="button"
          aria-label="Next month"
          onClick={() => goToMonth(shiftMonth(month, 1))}
          className="rounded-md border border-(--color-border) px-2.5 py-1 text-sm text-(--color-text-muted) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text)"
        >
          ▸
        </button>
        {month !== currentMonthKey() && (
          <button
            type="button"
            onClick={() => goToMonth(currentMonthKey())}
            className="ml-1 rounded-md px-2 py-1 text-xs text-(--color-text-faint) transition-colors hover:text-(--color-text-muted)"
          >
            Today
          </button>
        )}
      </div>

      <div className="mb-6 rounded-xl border border-(--color-border) bg-(--color-surface) p-5 sm:mb-8 sm:p-6">
        <p className="text-xs font-medium text-(--color-text-muted)">Ready to Assign</p>
        <p
          data-testid="ready-to-assign"
          className={`tabular-nums mt-1 text-3xl font-semibold tracking-tight sm:text-4xl ${
            readyToAssign < 0 ? 'text-(--color-negative)' : 'text-(--color-accent)'
          }`}
        >
          {formatMoney(budget.ready_to_assign)}
        </p>
      </div>

      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-(--color-text-muted)">Categories</h2>
        <button
          type="button"
          onClick={() => openNewCategory(null)}
          className="flex items-center gap-1 rounded-md border border-(--color-border) px-2 py-1 text-xs font-medium text-(--color-text-muted) transition-colors hover:bg-(--color-surface-hover) hover:text-(--color-text)"
        >
          <span aria-hidden className="text-sm leading-none">+</span> Category
        </button>
      </div>

      <div className="overflow-hidden rounded-xl border border-(--color-border)">
        {budget.categories.length === 0 ? (
          addingUnder === null ? (
            <ul>{renderNewCategoryRow(null)}</ul>
          ) : (
            <p className="px-4 py-6 text-center text-sm text-(--color-text-faint)">No categories yet.</p>
          )
        ) : (
          <>
            {/* Column header — desktop only; the mobile cards label their own stats. */}
            <div className="hidden items-center gap-4 border-b border-(--color-border) bg-(--color-surface) px-4 py-2 sm:flex">
              <span className="flex-1 text-xs font-medium tracking-wide text-(--color-text-muted) uppercase">
                Category
              </span>
              <span className={HEAD_CELL}>Spent</span>
              <span className={HEAD_CELL}>Available</span>
              <span className={HEAD_CELL}>Budgeted</span>
              {/* aligns the header cells with the rows, which carry a ⋮ here */}
              <span aria-hidden className="w-7 shrink-0" />
            </div>
            <ul className="divide-y divide-(--color-border)">
              {addingUnder === null && renderNewCategoryRow(null)}
              {topLevel.map((parent) => {
                const kids = childrenOf(parent.id)
                const hideKids = parent.is_group && collapsed.has(parent.id)
                return [
                  renderCategoryRow(parent, false, topLevel),
                  ...(addingUnder === parent.id ? [renderNewCategoryRow(parent.id)] : []),
                  ...(hideKids ? [] : kids.map((child) => renderCategoryRow(child, true, kids))),
                ]
              })}
              {orphans.map((orphan) => renderCategoryRow(orphan, true, orphans))}
            </ul>
            <div
              data-testid="budget-totals"
              className="flex flex-col gap-2 border-t-2 border-(--color-border) bg-(--color-surface) px-4 py-2.5 sm:flex-row sm:items-center sm:gap-4"
            >
              <span className="text-xs font-semibold tracking-wide text-(--color-text-muted) uppercase sm:flex-1">
                Total
              </span>
              <div className="grid grid-cols-3 gap-2 sm:contents">
                <div className="flex flex-col gap-0.5 sm:contents">
                  <span className={STAT_LABEL}>Spent</span>
                  <span className={`${NUM_CELL} font-semibold text-(--color-text)`}>
                    {formatMoney(budget.totals.spent)}
                  </span>
                </div>
                <div className="flex flex-col gap-0.5 sm:contents">
                  <span className={STAT_LABEL}>Available</span>
                  <span
                    className={`${NUM_CELL} font-semibold ${availableColor(Number(budget.totals.available))}`}
                  >
                    {formatMoney(budget.totals.available)}
                  </span>
                </div>
                <div className="flex flex-col gap-0.5 sm:contents">
                  <span className={STAT_LABEL}>Budgeted</span>
                  <span className="flex items-center justify-center tabular-nums text-sm font-semibold text-(--color-text) sm:w-28 sm:shrink-0">
                    {formatMoney(budget.totals.budgeted)}
                  </span>
                </div>
              </div>
              {/* matches the ⋮ gutter on the rows above */}
              <span aria-hidden className="hidden w-7 shrink-0 sm:block" />
            </div>
          </>
        )}

      </div>

      {manageError && (
        <p role="alert" className="mt-2 text-sm text-(--color-negative)">
          {manageError}
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
                <span className="shrink-0 text-right tabular-nums text-sm text-(--color-text-faint) sm:w-28">
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
