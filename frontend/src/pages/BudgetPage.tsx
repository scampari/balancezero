import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  type Budget,
  type TargetType,
  createCategoryWithAutoRefresh,
  getBudgetWithAutoRefresh,
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

export function BudgetPage() {
  const { accessToken, setAccessToken, isAuthChecked } = useAuth()
  const navigate = useNavigate()
  const [budget, setBudget] = useState<Budget | null>(null)
  const [newCategoryName, setNewCategoryName] = useState('')
  // '' = top-level; otherwise the parent category id as a string.
  const [newCategoryParent, setNewCategoryParent] = useState('')
  const [isCreatingCategory, setIsCreatingCategory] = useState(false)
  const [categoryError, setCategoryError] = useState<string | null>(null)
  // Local text state per category while the user is typing an allocation,
  // keyed by category id — lets the input hold an in-progress value
  // (including a temporarily-invalid one like "12.") without fighting the
  // server-confirmed value in `budget`.
  const [allocationDrafts, setAllocationDrafts] = useState<Record<number, string>>({})
  // Which category's target editor is open, plus its in-progress form values.
  const [targetEditorFor, setTargetEditorFor] = useState<number | null>(null)
  const [targetType, setTargetType] = useState<TargetType>('monthly')
  const [targetAmount, setTargetAmount] = useState('')
  const [targetDate, setTargetDate] = useState('')
  const [targetError, setTargetError] = useState<string | null>(null)
  const [isSavingTarget, setIsSavingTarget] = useState(false)

  function loadBudget(token: string) {
    return getBudgetWithAutoRefresh(token, setAccessToken).then((data) => setBudget(data))
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

    // Wait for AuthProvider's initial silent-refresh attempt to resolve
    // before concluding there's no session — accessToken starts null on
    // every mount regardless of whether a valid refresh cookie exists.
    if (!isAuthChecked) return

    if (!accessToken) {
      navigate('/login', { replace: true })
      return
    }

    loadBudget(accessToken).catch(() => {
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
    // Clear the draft either way — on success the server value takes over,
    // on failure we fall back to the last-known server value rather than
    // leaving a possibly-invalid draft stuck in the field.
    setAllocationDrafts((prev) => {
      const next = { ...prev }
      delete next[categoryId]
      return next
    })
    if (draft === '' || Number.isNaN(Number(draft))) return
    await setAllocationWithAutoRefresh(accessToken, setAccessToken, categoryId, CURRENT_MONTH, draft)
    await loadBudget(accessToken)
  }

  if (!budget) return <PageLoading />

  const readyToAssign = Number(budget.ready_to_assign)

  // Two-level hierarchy (enforced server-side): render each top-level
  // category followed by its own subcategories, indented. A subcategory
  // whose parent isn't in the list (shouldn't happen) falls through to the
  // end so it's never silently dropped.
  const topLevel = budget.categories.filter((c) => c.parent_id == null)
  const childrenOf = (parentId: number) => budget.categories.filter((c) => c.parent_id === parentId)
  const orphans = budget.categories.filter(
    (c) => c.parent_id != null && !budget.categories.some((p) => p.id === c.parent_id),
  )

  function renderCategoryRow(category: Category, isChild: boolean) {
    const available = Number(category.available)
    const draft = allocationDrafts[category.id]
    return (
      <li
        key={category.id}
        className={`flex flex-col gap-2 bg-(--color-surface) py-3 pr-4 transition-colors hover:bg-(--color-surface-hover) ${
          isChild ? 'pl-10' : 'pl-4'
        }`}
      >
        <div className="flex items-center justify-between gap-4">
          <span className={`text-sm ${isChild ? 'text-(--color-text-muted)' : 'text-(--color-text)'}`}>
            {isChild && <span className="mr-1.5 text-(--color-text-faint)">↳</span>}
            {category.name}
          </span>
          <div className="flex items-center gap-4">
            <span
              className={`tabular-nums w-28 text-right text-sm font-medium ${
                available < 0 ? 'text-(--color-negative)' : 'text-(--color-text)'
              }`}
            >
              {formatMoney(category.available)}
            </span>
            <label className="flex w-28 items-center justify-end gap-1.5">
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
          </div>
        </div>

        <div className="flex items-center justify-between gap-4">
          <span className="text-xs text-(--color-text-faint)">
            {category.target
              ? `Target: ${formatMoney(category.target.monthly_target_amount)}/mo` +
                (category.target.target_type === 'monthly'
                  ? ''
                  : ` (${formatMoney(category.target.target_amount)} ${
                      category.target.target_type === 'yearly'
                        ? 'this year'
                        : `by ${category.target.target_date}`
                    })`)
              : 'No target'}
          </span>
          <button
            type="button"
            onClick={() =>
              targetEditorFor === category.id ? setTargetEditorFor(null) : openTargetEditor(category)
            }
            className="rounded-md border border-(--color-border) px-2 py-1 text-xs text-(--color-text-muted) transition-colors hover:bg-(--color-surface-hover)"
          >
            {category.target ? 'Edit target' : 'Set target'}
          </button>
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
              className="rounded-md bg-(--color-accent) px-3 py-1 text-xs font-medium text-(--color-bg) transition-colors hover:bg-(--color-accent-hover) disabled:cursor-not-allowed disabled:opacity-60"
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
            <div className="flex items-center justify-between gap-4 border-b border-(--color-border) bg-(--color-surface) px-4 py-2">
              <span className="text-xs font-medium tracking-wide text-(--color-text-muted) uppercase">
                Category
              </span>
              <div className="flex items-center gap-4">
                <span className="w-28 text-right text-xs font-medium tracking-wide text-(--color-text-muted) uppercase">
                  Available to Spend
                </span>
                <span className="w-28 pr-2 text-right text-xs font-medium tracking-wide text-(--color-text-muted) uppercase">
                  Budgeted
                </span>
              </div>
            </div>
            <ul className="divide-y divide-(--color-border)">
              {topLevel.map((parent) => [
                renderCategoryRow(parent, false),
                ...childrenOf(parent.id).map((child) => renderCategoryRow(child, true)),
              ])}
              {orphans.map((orphan) => renderCategoryRow(orphan, true))}
            </ul>
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
            {topLevel.map((parent) => (
              <option key={parent.id} value={parent.id}>
                Subcategory of {parent.name}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={isCreatingCategory || !newCategoryName.trim()}
            className="rounded-md bg-(--color-accent) px-3 py-1.5 text-sm font-medium text-(--color-bg) transition-colors hover:bg-(--color-accent-hover) disabled:cursor-not-allowed disabled:opacity-60"
          >
            Add
          </button>
        </form>
      </div>
      {categoryError && (
        <p role="alert" className="mt-2 text-sm text-(--color-negative)">
          {categoryError}
        </p>
      )}
    </AppShell>
  )
}
