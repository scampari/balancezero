# Slicing: Category budget targets + explicit "To Be Budgeted" income

> Date: 2026-08-26
> Status: planning
> Branch: agent/plaid-test-planning

## What & Why
Adds two zero-based-budgeting features from the MVP backlog: (1) a per-category
budget target (monthly, yearly, or by a custom date) so a user can set a goal
and see progress toward it, and (2) an explicit "To Be Budgeted" tag on
transactions, replacing the current implicit rule (`ready_to_assign` =
uncategorized inflow − allocated) with a deliberate user action. Both extend
`budget-api.md`'s existing category/budget-view surface rather than
introducing new top-level resources.

("Available to Spend"/"Assigned" labels from the same backlog are pure
frontend copy against fields `GET /api/budget` already returns —
`available`/`allocated_this_month` — no spec change needed, skipped here.
Subcategories and Plaid connect/sync are already built, out of scope.)

## Spec changes
- `spec/budget-api.md` — modified — add `POST /api/categories/<id>/target`
  (create/replace target, supersedes prior target rather than deleting it)
  and `GET /api/categories/<id>/target` (current active target); `GET
  /api/budget`'s per-category shape gains target fields; `ready_to_assign`'s
  computation changes from "uncategorized inflow" to "transactions marked
  `is_income`".
- `spec/transactions.md` — modified — `PATCH /api/transactions/<id>` gains
  an `is_income` toggle (mutually exclusive with `category_id`); `GET
  /api/transactions` response gains `is_income`.

## Context changes
- None. No new architectural pattern — targets and TBB both extend the
  existing Category/Transaction model and the established ownership-check
  (404/403) pattern from `context/security-requirements.md`.

## Constraints
- **Target storage is a history, not a single row**: new `CategoryTarget`
  table (`category_id` FK, `target_type` enum `monthly|yearly|custom`,
  `target_amount`, `target_date` nullable — required for `custom`, forbidden
  for `monthly`/`yearly`, `created_at`, `superseded_at` nullable). Setting a
  new target sets `superseded_at` on the previous active one rather than
  deleting it — same supersede-not-delete pattern this project already uses
  for specs (`spec/README.md`). "Active" target = `superseded_at IS NULL`.
- **Backend computes the monthly contribution**: `GET /api/budget`'s
  per-category shape includes a computed `monthly_target_amount` — for
  `monthly`, equals `target_amount`; for `yearly`/`custom`,
  `target_amount ÷ months remaining` (months from current month through
  `target_date`, or through Dec of the current year for `yearly`). One
  source of truth in the backend, not duplicated in the frontend.
- **Target applies to any category regardless of hierarchy** — a
  subcategory can have its own target independent of its parent's, no
  special-casing (matches `budget-api.md`'s existing "no budget-math change
  based on hierarchy" principle).
- **TBB is a synthetic flag, not a real Category row**: new
  `Transaction.is_income` boolean (default `False`), not an auto-created
  category. Reuses the existing `PATCH /api/transactions/<id>` endpoint —
  the dropdown's "To Be Budgeted" option sends `{"is_income": true,
  "category_id": null}` instead of a real `category_id`. `is_income=true`
  and a non-null `category_id` are mutually exclusive — `400` if both are
  set.
- **No per-transaction backfill — a single starting-balance reconciliation
  per account instead (decided 2026-08-26).** Existing transactions are
  never retroactively retagged `is_income`. Instead, each `Account` gets
  exactly one synthetic `Transaction` created at ship time: `is_income:
  true`, `amount` = the account's current balance, `description: "Starting
  Balance"`, `category_id: null`, `posted_at` = the day it's created. This
  reuses the already-designed `is_income` → `ready_to_assign` mechanism
  unchanged — no formula change in `budget-api.md` needed, this is purely a
  one-time data-seeding concern. Matches the standard budgeting-app pattern
  (YNAB's own "Starting Balance" transaction) for reconciling a bank
  balance into a budget without importing transaction history.
  - **Scope:** one-off data migration/script for the accounts that exist
    today, run once when this slice ships. NOT a new API endpoint and NOT
    automatic behavior on every future account connection — auto-creating
    a starting-balance transaction when a *new* account connects is a
    `plaid-connect.md`/`accounts-api.md` concern, out of scope for this
    plan (see Non-Goals). A user linking a new account after this ships
    still explicitly marks their first paycheck (or however they choose)
    as "To Be Budgeted" — this reconciliation only solves the one-time
    "I already have money in the bank" cold-start problem.
- **Manual only** — no auto-detection of income transactions by sign,
  payee, or amount. Consistent with the MVP's existing "no
  auto-categorization" non-goal (`context/mvp-scope.md`).

## Non-Goals
- No historical target-progress analytics/reporting (e.g. "hit your target
  4 months in a row") — just current target + computed monthly amount.
- No auto-categorization or auto-detection of income transactions.
- No per-transaction backfill of pre-existing transactions to
  `is_income=true` — only the one-time per-account starting-balance
  reconciliation described in Constraints.
- No automatic starting-balance transaction on future new-account
  connections — that's a `plaid-connect.md`/`accounts-api.md` follow-up,
  not this plan.
- No target editing UI beyond create/replace — no partial-update of a
  single target field.

## Build skills
- None new — same Flask + SQLAlchemy + pytest stack as `budget-api.md`,
  same ownership-check and upsert/supersede patterns already established.

## First slice
- `spec/budget-api.md` (target endpoints) — additive only, no change to
  existing endpoint behavior, lowest risk, entry point.
- `spec/budget-api.md` (`ready_to_assign` formula change) + `spec/
  transactions.md` (`is_income` toggle) — second slice, together (the
  formula change is meaningless without the toggle that feeds it). Higher
  risk: changes existing `GET /api/budget` behavior for real data.

## Open Questions
- Resolved 2026-08-26: no per-transaction backfill; a one-time
  per-account "Starting Balance" `is_income` transaction reconciles the
  cold-start gap instead (see Constraints).
- New: does the one-time starting-balance script run against the current
  `Account.balance` column directly, or does it need a fresh Plaid sync
  first to make sure that balance is current? Assumed "use whatever
  `Account.balance` holds at script-run time" — flag if a forced sync
  should happen first.

## Test planning result

### Spec files modified
- `spec/budget-api.md` — added `POST`/`GET /api/categories/<id>/target`
  contracts (with 9 error cases covering type/amount/date validation and
  ownership), changed `GET /api/budget`'s `ready_to_assign` computation and
  added `target` to its per-category shape. Status → `in-progress`.
- `spec/transactions.md` — added `is_income` toggle to `PATCH
  /api/transactions/<id>` (mutual exclusivity with `category_id` enforced
  as a `400`) and `is_income` to `GET /api/transactions`'s response shape.
  Status → `in-progress`.

### Spec files created
- None — both features extend existing specs, per the plan's "default to
  modifying" call.

### Mock boundaries
- All real. No external systems involved — pure Postgres (per
  `context/testing.md`'s existing "real Postgres, never SQLite" rule), same
  as every other `budget-api.md`/`transactions.md` contract.

### Context updates
- None. No new architectural pattern introduced.

### Test infrastructure notes
- New `CategoryTarget` model + migration needed before tests can be
  written (mirrors `BudgetAllocation`'s shape/pattern).
- `Transaction.is_income` column + migration needed (mirrors the existing
  `category_id` nullable-FK-plus-boolean-flag style already on the model).
- First slice (target endpoints) has zero dependency on the second
  (`is_income`/`ready_to_assign`) — can be built and tested independently,
  per the plan's "First slice" section.
