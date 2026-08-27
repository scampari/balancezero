# Slicing: category groups (collapsible parent totals)

> Date: 2026-08-27
> Status: built
> Branch: changes/014-category-groups

## What & Why
The user wants a top-level category that has children to stop being an
editable line and instead act as a **collapsible group total** of its
children's budgeted / spent / available. This deliberately reverses
`spec/budget-api.md`'s "no roll-up / parent and child are independent line
items" design.

Chosen scope (from the user): **block them, YNAB-style** — a category with
children can't be allocated to or have transactions assigned to it; pre-
existing parent-level amounts fold into the group total. Collapsed state
**remembered per browser**.

## Spec changes
- `spec/budget-api.md` — `GET /api/budget` entry gains `is_group`; a group's
  columns sum its children (+ own legacy); `POST .../allocations` on a
  group → `400`. Reverses the "no roll-up" bullet.
- `spec/transactions.md` — assigning a transaction to a group → `400`.

## Context changes
- None (no new architectural pattern — group-ness is derived at read time
  from `parent_id` + `archived`, no schema change).

## Constraints
- **Group = a top-level category (`parent_id IS NULL`) with ≥1
  non-archived child.** Purely derived — no column, no migration. An
  archived child doesn't count.
- **`GET /api/budget`:** each entry gets `"is_group": bool`. A group's
  `allocated_this_month` / `spent_this_month` / `available` = the parent's
  own value **plus** the sum over its non-archived children's own values
  (folding in any legacy parent-level allocation/spend so nothing
  vanishes). A group's `target` is `null`. `totals` keeps summing each
  category's *own* values, so group + children are never double-counted.
- **`POST /api/categories/<id>/allocations`** on a category with
  non-archived children → `400`.
- **`PATCH` and `POST /api/transactions`** with a `category_id` that has
  non-archived children → `400`. `api_helpers.infer_category_id` (013)
  also excludes group categories from auto-match.
- **Shared helper `api_helpers.category_has_children(category_id)`.**
- **Frontend `BudgetPage`:** a group row renders a ▸/▾ collapse toggle, a
  read-only summed "Budgeted" figure (no `<input>`), no "Set target"
  button; children are hidden while collapsed. Collapsed category ids
  persist to `localStorage['bz.budget.collapsed']` (same mechanism as the
  theme picker). `BudgetCategory.is_group` added to `client.ts`.
- **Frontend `TransactionsPage`:** group categories filtered out of both
  category `<select>`s (`assignableCategories`).

## Non-Goals
- Nested groups / >2 levels (still capped at one level of nesting).
- Rolling a group's *target* up from children.
- Preventing a category that already has allocations/transactions from
  gaining a child — it can; the old amounts just fold into the group total
  and further edits are blocked.
- A migration to move parent-level allocations onto a child.

## Slices
- **014-A** backend — `api_helpers.category_has_children`;
  `budget_api.get_budget` group summing + `is_group`; `set_allocation`
  guard; `transactions_api` PATCH/POST guard; `infer_category_id` group
  exclusion. Tests: `tests/test_budget_api.py` +8,
  `tests/test_transactions.py` +2.
- **014-B** frontend — `client.ts` `is_group`; `BudgetPage.tsx` collapse
  toggle + read-only group figure + localStorage; `TransactionsPage.tsx`
  picker filter. e2e `budget-management.spec.ts` +1.

## Verification
- `venv/bin/pytest` — 208 passed / 6 skipped (was 200/6).
- `cd frontend && npm run build && npm run lint` clean (2 pre-existing
  warnings).
- `npm run test:e2e` — 25 passed (24 prior + 1: group row has no assign
  input, shows summed $400.00 / $344.75, collapse hides children and
  persists across navigation).
