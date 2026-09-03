---
status: built
depends_on: []
---

# Reports API: spending-habits aggregation

## Does
Adds one read-only endpoint, `GET /api/reports`, returning every dataset the
`/reports` page renders: spending by category over time, income vs. expense
per period, period-over-period total spend, and top merchants. Aggregation
only — no schema change. Rendered client-side with hand-rolled inline SVG
(no charting library).

Customizable (changes/020): filter by account, filter by category/group
(a group id expands to its children), pick the period **grain** (week /
month / quarter / year), and include or exclude transfers.

## Done when
- A user can request a report for a month range and get per-bucket,
  per-category, and per-merchant rollups back as JSON.
- Omitting the range defaults to the last 6 months (inclusive of the
  current month). Omitting `grain` defaults to `month`.
- Every array is zero-filled across the requested buckets — a bucket with
  no data still appears, with zeros.
- All money values are 2-decimal strings, same as every other money field
  in the API.
- The demo user can view reports (read-only, own rows only — makes the
  public demo useful; see Notes).
- `accounts` / `categories` scope every dataset; an unknown or foreign id
  → `400`. `exclude_transfers` defaults to `true` — it hides only
  **uncategorized** transfers (`transfer = true AND category_id IS NULL`);
  a transfer the user has filed under a category is real spending and stays
  in, matching `spec/budget-api.md` changes/028 (changes/029).
  `exclude_transfers=false` includes every transfer, categorized or not.
- The response echoes the applied filters under `filters` so the page can
  restore its state from the URL.

## Integration test contract

### GET /api/reports

**Setup:** An authenticated user with some `Transaction` rows (via owned
`Account`s), optionally categorized, optionally `is_income`.
**Action:** `GET /api/reports?from=YYYY-MM&to=YYYY-MM&grain=month&accounts=1,2&categories=4&exclude_transfers=true`
(all query params optional).
**Input:** `from` / `to` are `YYYY-MM` (the range bounds; buckets are derived
from them at the chosen grain). Default: `to` = current month, `from` = 5
months earlier. `grain` ∈ `week|month|quarter|year` (default `month`).
`accounts` / `categories` are comma-separated owned ids. `exclude_transfers`
∈ `true|false` (default `true`).
**Expected output:** `200`, JSON:
```
{
  "from": "2026-03", "to": "2026-08",
  "grain": "month",
  "buckets": ["2026-03", ..., "2026-08"],   // key format per grain: YYYY-Www / YYYY-MM / YYYY-Qn / YYYY
  "filters": {"accounts": [1,2], "categories": [4], "grain": "month", "exclude_transfers": true},
  "spending_by_category": [
    {"category_id": 12|null, "category": "Groceries"|"Uncategorized",
     "parent_id": 4|null, "total": "812.55",
     "by_bucket": [{"bucket": "2026-03", "amount": "120.00"}, ...]}  // zero-filled, in `buckets` order
  ],
  "income_vs_expense": [{"bucket": "2026-03", "income": "5000.00", "expense": "3120.55", "net": "1879.45"}, ...],
  "month_over_month_spend": [   // key name kept for back-compat; it is period-over-period
    {"bucket": "2026-03", "total": "3120.55", "change": null, "change_pct": null},   // first bucket: nulls
    {"bucket": "2026-04", "total": "3450.10", "change": "329.55", "change_pct": "0.1056"}, ...
  ],
  "top_merchants": [{"description": "AMAZON", "total": "402.11", "count": 9}, ...]   // <= 10, expense-only
}
```
Definitions (consistent with `budget_api`):
- **expense** = `SUM(-amount) WHERE amount < 0`, reported as a positive number.
- **income** = `SUM(amount) WHERE is_income`.
- **net** = `SUM(amount)` over every transaction that month (signed) — so a
  non-income refund (positive, `is_income = false`) nets in here only, not
  into `income`.
- `spending_by_category` is expense-only, ordered by `total` descending,
  with a `category_id: null` "Uncategorized" bucket when applicable.
- `top_merchants` groups by exact `Transaction.description`, expense-only,
  top 10 by magnitude over the whole range.

**Side effects:** None (read-only).

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `from` or `to` is not a valid `YYYY-MM`, Then** `400`.
- **When `from` is after `to`, Then** `400`.
- **When the range exceeds the grain's bucket cap** (week 53, month 24,
  quarter 12, year 10)**, Then** `400` (query-cost bound).
- **When `grain` is not one of the four values, Then** `400`.
- **When `accounts` / `categories` contains a non-integer, or an id the
  user doesn't own, Then** `400`.
- **When the user has no matching transactions, Then** `200` with
  zero-filled arrays (`spending_by_category` and `top_merchants` are `[]`;
  `income_vs_expense` / `month_over_month_spend` have one zeroed row per
  month). Not a 404.

#### `exclude_transfers` cases (changes/029)
- **When `exclude_transfers` is `true` (default) and a `transfer = true`
  transaction has a `category_id`, Then** it is included in every dataset
  (`spending_by_category`, `income_vs_expense` `expense` / `net`,
  `month_over_month_spend`, `top_merchants`) like any other categorized
  expense.
- **When `exclude_transfers` is `true` (default) and a `transfer = true`
  transaction has no `category_id`, Then** it is excluded from every
  dataset (unchanged from 020).
- **When `exclude_transfers=false`, Then** both categorized and
  uncategorized transfers are included (unchanged from 020).
- The `filters.exclude_transfers` echo is still just the boolean the caller
  sent (or the `true` default) — no new field discloses the hidden
  uncategorized rows.

## Tests
- `tests/test_reports_api.py` — one test per contract line: auth required;
  default 6-month range; explicit range; invalid `from` → 400; `from > to`
  → 400; range too large → 400; empty user → zero-filled; category totals +
  monthly breakdown (zero-filled, ordered); Uncategorized bucket;
  income/expense/net per month (refund nets into `net` only); MoM change +
  pct, first month null; top merchants grouped / expense-only / capped;
  isolated per user; money values are strings; demo user can view.
- `tests/test_reports_api.py` § `"test_reports_default_includes_a_categorized_transfer"`
  — covers § exclude_transfers case 1 (changes/029): a categorized
  `transfer = true` row counts in `expense`, `spending_by_category`, and
  `top_merchants`, while an uncategorized transfer in the same window does
  not. Committed red 2026-09-03 (`expense` is `40.00`, not `140.00`).
  Cases 2–3 ("unchanged from 020") stay covered by
  `"test_reports_excludes_transfers_by_default_and_includes_on_request"`.
- `frontend/e2e/reports.spec.ts` + `seed_e2e_reports.py` — dedicated user
  `sam-reports`, 4 months of categorized transactions + monthly income;
  `/reports` nav link, panels render, range pickers present, seeded
  merchant/category surface as text, narrowing the range re-fetches.

## Notes
- **Single combined endpoint**, not four — one shared range, one page, ~4
  grouped queries. Fewer round-trips; the page has no use for one dataset
  without the others.
- **24-month cap** is a product default (query cost), adjustable — not a
  hard product rule.
- **Demo user is allowed.** No `is_demo` guard: the endpoint reads only the
  caller's own rows (`Account.user_id == uid`), there's no cross-user path,
  and reports make the public demo more useful. This is a deliberate
  exception, consistent with `context/security-requirements.md`'s
  per-user-isolation rule (which it still obeys).
- **Postgres-specific** (`date_trunc` / `to_char`) — fine, prod and the
  test DB are both Postgres; SQLite is local-dev convenience only.
- **Mock boundary:** all real. Pure Postgres, same as `spec/budget-api.md`.

## Changes
- 009 (2026-08-27) — created + built. `reports_api.py` blueprint
  registered in `app.py`; `tests/test_reports_api.py` (15);
  `frontend/src/pages/ReportsPage.tsx` + `frontend/src/components/charts/*`
  (hand-rolled SVG) + `client.ts` types + `/reports` route + nav link. Full
  backend suite 177 passed / 5 skipped; e2e 21 passed. See
  `changes/009-reporting/plan.md`.
- 029 (2026-09-03) — contract landed by test-planning. `exclude_transfers`
  (default `true`) stops hiding **categorized** transfers — the filter
  becomes `transfer = false OR category_id IS NOT NULL`, matching
  `spec/budget-api.md` 028 (a categorized transfer is real spending).
  `exclude_transfers=false` is unchanged (everything in). One SQL clause in
  `reports_api.py`; `tests/test_reports_api.py`
  `test_reports_default_includes_a_categorized_transfer`. Part of
  `changes/029-credit-card-debt-payoff`. Built 2026-09-03 — the
  `exclude_transfers` filter is now
  `or_(Transaction.transfer.is_(False), Transaction.category_id.isnot(None))`.
- 020 (2026-08-27) — customization. `GET /api/reports` gains `grain`
  (`week`/`month`/`quarter`/`year`, default `month`), `accounts`,
  `categories` (a group id expands to its non-archived children), and
  `exclude_transfers` (default `true`). Response renamed `months`→`buckets`
  and per-row `month`→`bucket` (`by_month`→`by_bucket`); adds `grain` and a
  `filters` echo. The flat 24-month cap became a per-grain bucket-count cap.
  `reports_api.py` rewrite; `tests/test_reports_api.py` +10;
  `ReportsPage.tsx` filter bar (grain segmented control, account/category
  multi-selects, exclude-transfers toggle) with state in the URL query
  string; `MonthBars` takes a `formatLabel`; `chartScale.bucketLabel`.
  `seed_e2e_reports.py` + `reports.spec.ts` +2. Also converted
  `seed_e2e_budget.py` to rebuild-every-run (the spec mutates the tree) and
  added a render wait to the reorder e2e — both pre-existing flakes.
