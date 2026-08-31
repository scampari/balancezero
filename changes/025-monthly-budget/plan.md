# Slicing: month-separated budget (future budgeting + overspend rollover)

> Date: 2026-08-31
> Status: built
> Branch: changes/025-monthly-budget

## What & Why
The budget is meant to be zero-based and envelope-style, but the view was not
really separated by month. `GET /api/budget`'s `available` was an all-time
figure (`Σ all allocations + Σ all signed transactions`, month-independent) and
`ready_to_assign` was a single global number. The user wants a true monthly
budget: navigate between months, assign money into a future month, and have a
category that overspends (or underspends) in one month carry that balance into
the next.

Decisions confirmed with the user:
- **Ready to Assign is month-scoped** — income through the end of the viewed
  month minus allocations for that month or earlier.
- **Overspend rolls inside the category** — the negative `available` carries
  forward as next month's starting balance; `ready_to_assign` is never touched
  by overspending. (Matches the pre-existing envelope math, just re-scoped to a
  month boundary.)
- **Month nav = prev/next stepper** with a "Today" affordance; the viewed month
  lives in the URL (`?month=YYYY-MM`), absent for the current month.

No migration: `BudgetAllocation.month` and `Transaction.posted_at` already carry
everything needed.

## Semantics (viewed month M, `end` = first day of M+1)
- `available` = `Σ(allocations WHERE month <= M) + Σ(signed txns WHERE posted_at < end)`.
- `rollover` (new) = `available − allocated_this_month − spent_this_month` = the
  carry-in from prior months (negative = overspent through end of last month).
- `ready_to_assign` = `Σ(is_income txns WHERE posted_at < end) − Σ(allocations WHERE month <= M)`.
- Groups sum their children's values, `rollover` included.
- Credit-card fold (`_by_card`) is bounded to `posted_at < end` too.

## Spec changes
- `spec/budget-api.md` — `GET /api/budget`: entry + `totals` gain `rollover`;
  `available` and `ready_to_assign` redefined as month-bounded; the 006
  "cumulative, not month-scoped" note marked superseded; `## Changes` +
  `## Tests` entries for 025.

## Context changes
- None (no new architectural pattern; all derived at read time).

## Files
- `budget_api.py` — `get_budget` only.
- `tests/test_budget_api.py` — +9 tests (later-month exclusion, `rollover`
  positive/negative, month-scoped `ready_to_assign`, future-allocation
  isolation, `totals.rollover`, group rollover, payment-envelope month bound).
- `frontend/src/api/client.ts` — `BudgetCategory` / `BudgetTotals` gain `rollover`.
- `frontend/src/pages/BudgetPage.tsx` — month stepper (URL `?month=`), per-row
  rollover line, allocations write to the viewed month.
- `frontend/e2e/budget-management.spec.ts` — +1 test (assign ahead, current
  month untouched).

## Verification
- `pytest tests/test_budget_api.py`, then full `pytest`.
- `npm run lint` + `tsc -b` + `npm run test:e2e` in `frontend/`.
- Manual: `GET /api/budget?month=` for two adjacent months after allocating /
  spending in the earlier one — next month's `rollover` equals the prior
  month's `available`; `ready_to_assign` differs by month.
