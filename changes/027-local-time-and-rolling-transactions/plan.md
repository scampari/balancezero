# Slicing: local-time "current month" + rolling transactions window

> Date: 2026-09-01
> Status: built
> Branch: changes/027-local-time-and-rolling-transactions

## What & Why
Two linked bugs, both from deriving "today" from UTC:

1. The budget's "current month" came from `new Date().toISOString().slice(0, 7)`
   — UTC. West of Greenwich, near midnight, the budget jumped to the next
   month while the user was still in the previous one locally.
2. The transactions page was locked to the current calendar month (server
   `date.today()`, also UTC) with no navigation, so at the month boundary the
   previous month's transactions vanished from view.

Decisions (from the user):
- **Timezone = browser local**, no setup selector. The device already knows;
  a stored IANA zone only adds a migration + settings UI and can drift.
- **Transactions = rolling window**, not a single month. Show the last 60 days
  anchored to the viewer's local today.

## Changes
- `spec/transactions.md` — `GET /api/transactions` gains `?since=YYYY-MM-DD`
  (on-or-after, no upper bound); response echoes `since` instead of `month`
  when used; invalid `since` → 400. `month` unchanged and still the default.
- No context/ change, no migration.

## Files
- `transactions_api.py` — `list_transactions`: `since` branch before the
  existing `month` handling; `since` wins if both present.
- `frontend/src/lib/dates.ts` (new) — `localMonthKey` / `localDateKey` /
  `localDateDaysAgo`, built from local `Date` getters, never `toISOString`.
- `frontend/src/pages/BudgetPage.tsx` — `currentMonthKey()` → `localMonthKey()`.
- `frontend/src/pages/TransactionsPage.tsx` — fetch `{ since: localDateDaysAgo(60) }`,
  `todayISO()` → `localDateKey()`, "Last 60 days" caption + empty state.
- `frontend/src/api/client.ts` — `getTransactions` takes `{ month?, since? }`;
  `TransactionsResponse.month` now optional, `since` added.
- `tests/test_transactions.py` +3.

## Verification
- `pytest` — 276 passed / 7 skipped.
- `npm run lint` + `tsc -b` clean; Playwright e2e 31 passed.
- Manual: set the OS clock near a month boundary (or spoof TZ) — the budget
  stays on the local month; `GET /api/transactions?since=<45d ago>` returns
  entries from the prior month.
