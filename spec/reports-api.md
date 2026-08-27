---
status: built
depends_on: []
---

# Reports API: spending-habits aggregation

## Does
Adds one read-only endpoint, `GET /api/reports`, returning every dataset the
`/reports` page renders: spending by category over time, income vs. expense
per month, month-over-month total spend, and top merchants. Aggregation
only — no schema change. Rendered client-side with hand-rolled inline SVG
(no charting library).

## Done when
- A user can request a report for a month range and get per-month,
  per-category, and per-merchant rollups back as JSON.
- Omitting the range defaults to the last 6 months (inclusive of the
  current month).
- Every array is zero-filled across the requested months — a month with no
  data still appears, with zeros.
- All money values are 2-decimal strings, same as every other money field
  in the API.
- The demo user can view reports (read-only, own rows only — makes the
  public demo useful; see Notes).

## Integration test contract

### GET /api/reports

**Setup:** An authenticated user with some `Transaction` rows (via owned
`Account`s), optionally categorized, optionally `is_income`.
**Action:** `GET /api/reports?from=YYYY-MM&to=YYYY-MM` (both query params
optional).
**Input:** `from` / `to` are `YYYY-MM`. Default: `to` = current month,
`from` = 5 months earlier.
**Expected output:** `200`, JSON:
```
{
  "from": "2026-03", "to": "2026-08",
  "months": ["2026-03", ..., "2026-08"],
  "spending_by_category": [
    {"category_id": 12|null, "category": "Groceries"|"Uncategorized",
     "parent_id": 4|null, "total": "812.55",
     "by_month": [{"month": "2026-03", "amount": "120.00"}, ...]}  // zero-filled, in `months` order
  ],
  "income_vs_expense": [{"month": "2026-03", "income": "5000.00", "expense": "3120.55", "net": "1879.45"}, ...],
  "month_over_month_spend": [
    {"month": "2026-03", "total": "3120.55", "change": null, "change_pct": null},   // first month: nulls
    {"month": "2026-04", "total": "3450.10", "change": "329.55", "change_pct": "0.1056"}, ...
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
- **When the range exceeds 24 months, Then** `400` (query-cost bound).
- **When the user has no matching transactions, Then** `200` with
  zero-filled arrays (`spending_by_category` and `top_merchants` are `[]`;
  `income_vs_expense` / `month_over_month_spend` have one zeroed row per
  month). Not a 404.

## Tests
- `tests/test_reports_api.py` — one test per contract line: auth required;
  default 6-month range; explicit range; invalid `from` → 400; `from > to`
  → 400; range too large → 400; empty user → zero-filled; category totals +
  monthly breakdown (zero-filled, ordered); Uncategorized bucket;
  income/expense/net per month (refund nets into `net` only); MoM change +
  pct, first month null; top merchants grouped / expense-only / capped;
  isolated per user; money values are strings; demo user can view.
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
