# Slicing: spending-habits reporting

> Date: 2026-08-27
> Status: built
> Branch: changes/009-reporting

## What & Why
The app only ever showed the current month. The user wants to track
spending habits over time. `budget_api.get_budget` already had the reusable
aggregation shape (`SUM(amount) JOIN Account ON user_id WHERE posted_at in
[start,end)`), and `BudgetAllocation` already holds per-month history — but
there was no endpoint that returned cross-month rollups, and no charts.

## Spec changes
- `spec/reports-api.md` — created — `GET /api/reports` contract: combined
  endpoint, optional `from`/`to` (`YYYY-MM`), four datasets, zero-fill,
  400 matrix, demo allowed. Status `built`.

## Context changes
- None. No new architectural pattern — a read-only aggregating blueprint,
  same stack and query shape as `budget_api`.

## Constraints
- **One combined endpoint**, `GET /api/reports` — one shared range, four
  datasets (`spending_by_category`, `income_vs_expense`,
  `month_over_month_spend`, `top_merchants`). ~4 grouped queries, pivoted
  in Python.
- **Sign/definitions match `budget_api`**: expense = `SUM(-amount) WHERE
  amount < 0` (positive); income = `SUM(amount) WHERE is_income`; net =
  `SUM(amount)` signed (a non-income refund nets into `net` only). Money =
  2-dp strings via a `_money()` that quantizes to cents.
- **Range**: default last 6 months incl. current; `YYYY-MM` params;
  `400` on bad format / `from > to` / span > 24 months; empty data → `200`
  zero-filled, not `404`.
- **Demo user allowed** — no `is_demo` guard. Reads only the caller's own
  rows; no cross-user path; makes the public demo useful. Stated in the
  spec Notes against `security-requirements.md:10-11`.
- **Charts are hand-rolled inline SVG** — no charting dependency. Two
  primitives cover all four datasets: `MonthBars` (single/grouped vertical
  bars per month) and `HBarList` (horizontal proportional bars, plain
  divs). Bars inherit `currentColor` from a per-series text-color utility;
  structure uses `--color-border` / `--color-text-muted`. No hex, no
  `getComputedStyle` — theme-aware for free (changes/010's palette).
- **Postgres-only** aggregation (`date_trunc` / `to_char`) — prod + tests
  are Postgres.

## Non-Goals
- Net-worth / balance-over-time — `Account` has no balance history table.
- Budget-vs-actual trend — the data exists (`BudgetAllocation` per month)
  but it's a separate report, not in this slice.
- Per-report endpoints, CSV export, custom date (not month) ranges,
  saved report presets.
- A charting library.

## Slices
- **009-A** backend — `reports_api.py` + `app.py` registration;
  `spec/reports-api.md`; `tests/test_reports_api.py` (15).
- **009-B** frontend — `client.ts` (`ReportsResponse` + friends,
  `getReports`); `ReportsPage.tsx`; `components/charts/`
  (`chartScale.ts`, `MonthBars.tsx`, `HBarList.tsx`); `/reports` route;
  `AppShell.tsx` nav link. e2e `reports.spec.ts` + `seed_e2e_reports.py`.

## Verification
- `venv/bin/pytest` — 177 passed / 5 skipped (was 162/5).
- `cd frontend && npm run build && npm run lint` clean (2 pre-existing
  `only-export-components` warnings).
- `npm run test:e2e` — 21 passed (19 prior + 2 reports).
- Manual: `/reports` as `demo` and as a real user; panels render; changing
  the range re-fetches; every theme (charts stay legible).
