# Slicing: target trackers + category management + budget-view columns

> Date: 2026-08-27
> Status: in-progress
> Branch: agent/006-target-trackers

## What & Why
Follows slice 005 (category targets + "To Be Budgeted"). Closes the next
batch of budget-view gaps the user asked for:

1. **Target trackers** — for a `yearly`/`custom` goal, surface how much to
   assign *this month* to stay on pace, accounting for money already set
   aside (`needed_this_month`), not just the progress-blind
   `target ÷ months`.
2. **Category management** — rename, archive (never delete — a delete would
   orphan the `category_id` on historical transactions and allocations),
   reparent, and manually reorder categories.
3. **Cleaner budget layout** — one line per category, aligned amount
   columns.
4. **Monthly Spent column** — per-category spend for the viewed month
   (`spent_this_month`); previously only an all-time sum existed, private to
   `available`.
5. **Totals row** — total Budgeted / Spent / Available across active
   categories.

## Spec changes
- `spec/budget-api.md` — modified —
  - new `PATCH /api/categories/<int:category_id>` (rename / `parent_id` /
    `archived` / `position`), with the full 400/403/404/409 matrix.
  - `GET /api/budget` response: `categories` becomes active-only ordered by
    `(position, id)`; new `archived_categories` array; per-entry
    `spent_this_month` / `position` / `archived`; new top-level `totals`;
    `target` embed gains `months_remaining` / `funded` /
    `needed_this_month` / `progress` (the four 005 fields keep their exact
    meaning so 005's target tests stay green).
  - Notes: archive-not-delete rationale, sibling `position` re-pack rule,
    `available` cumulative vs `spent_this_month` month-scoped, target
    progress formulas.
- Status stays `built` — additive, no regression.

## Context changes
- None. No new architectural pattern — `archived` mirrors the existing
  soft-state style (`CategoryTarget.superseded_at`), `position` was already
  on the model, ownership checks reuse `_get_owned_category`.

## Constraints
- **Archive, never delete.** New `Category.archived` (Boolean, default
  `false`) + migration `b2c3d4e5f6a7` (chained off `a1b2c3d4e5f6`,
  `batch_alter_table` + `server_default=sa.false()` then dropped — same
  shape as `a1b2c3d4e5f6_add_transaction_is_income.py`). Archived rows keep
  every transaction/allocation association. Archiving a parent that still
  has a non-archived child → `400`; unarchiving a child while its parent is
  archived → `400`.
- **Positions are re-packed, not sparse.** `PATCH` with `position` (or any
  reparent) renumbers the affected sibling group(s) to a gap-free
  `0..n-1` sequence in the same transaction (`_pack_siblings`). Avoids
  float gaps / collisions. A reparent lands the moved category at the end
  of its destination group before an explicit `position` in the same
  request is applied.
- **`funded` = envelope balance** for a dated target — the category's
  current `available` (`max(0, ...)`), YNAB-style: spending against the
  category lowers `funded` so `needed_this_month` rises. `monthly` targets
  use `allocated_this_month` as `funded`.
- **No hierarchy math.** Parent and child stay independent line items;
  `totals` is a flat sum over non-archived categories, no roll-up
  (consistent with `spec/budget-api.md`'s existing principle).
- **`_month_bounds` moves to `api_helpers.py`** (`month_bounds`) so
  `budget_api.py` and `transactions_api.py` share one implementation.

## Non-Goals
- No category delete.
- No drag-and-drop reorder — up/down controls only this slice.
- No >2 hierarchy levels; no cross-parent reorder in one action.
- No multi-month / historical target analytics; `needed_this_month` is the
  only new derived target number.
- No change to `ready_to_assign` semantics.
- `monthly_target_amount` keeps its 005 (progress-blind) meaning.

## Build skills
- None new — same Flask + SQLAlchemy + pytest stack, same
  ownership-check / upsert / supersede patterns already established.

## First slice
- **006-A** `spec/budget-api.md` — `PATCH /api/categories/<id>` +
  `archived` column + `GET /api/budget` active/archived split. Lowest risk
  entry point; the `PATCH` is additive and the split is a filter.
- **006-B** `spec/budget-api.md` — `GET /api/budget` computed columns
  (`spent_this_month`, `totals`, target progress). Depends on 006-A's
  archived filter (totals exclude archived). Ships in the same backend PR.
- **006-C** frontend — `BudgetPage.tsx` redesign (one-line rows, Spent
  column, totals row, collapsed Archived section, target progress bar +
  "assign $X more", per-row rename/move/reorder/archive controls) +
  `client.ts` types & `patchCategory`. e2e coverage only, matching how
  005's frontend landed. Second PR.

## Test planning result

### Spec files modified
- `spec/budget-api.md` — `PATCH /api/categories/<id>` contract + error
  matrix; expanded `GET /api/budget` shape; four new Notes bullets; Tests
  and Changes entries. Status stays `built`.

### Spec files created
- None.

### Mock boundaries
- All real. Pure Postgres (`context/testing.md`'s real-DB rule), same as
  every other `budget-api.md` contract.

### Context updates
- None.

### Test infrastructure notes
- `Category.archived` column + migration `b2c3d4e5f6a7` needed before the
  archive tests can arrange state.
- 25 integration tests added to `tests/test_budget_api.py` (PATCH section +
  `GET /api/budget` 006 additions), all AAA / real Postgres, local helper
  style. Full suite 128/128, 9 skipped (Plaid sandbox).
