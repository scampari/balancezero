---
status: planned
depends_on: [transactions.md, frontend-app.md]
---

# Transactions UI: list + categorize page

## Does
The frontend counterpart to `transactions.md` — a `/transactions` page where a logged-in user can see their transactions and change a transaction's category via a dropdown, without a page reload. This is the piece that actually makes the app "something to interact with," per the phase's stated goal.

## Done when
- A user can navigate to `/transactions` and see real transactions from the real API (not hardcoded).
- Each transaction shows a category selector; changing it calls the real `PATCH /api/transactions/<id>` and the UI reflects the new category without a full page reload.
- Uncategorized transactions are visibly distinguishable (e.g. an "Uncategorized" option/label), not just a blank dropdown.

## Integration test contract

Playwright e2e, same real-backend/real-browser approach as `frontend-app.md`.

### Transactions page shows real seeded data

**Setup:** `seed_e2e.py` seeds one account, one category ("Groceries"), and one uncategorized transaction alongside the existing test user (extends the current seed, which only creates a user).
**Action:** Log in, navigate to `/transactions`.
**Expected output:** The seeded transaction's description and amount are visible on the page.

### Changing a transaction's category persists

**Setup:** Same seeded state — one uncategorized transaction, one category available to assign.
**Action:** On `/transactions`, select "Groceries" from the seeded transaction's category dropdown.
**Expected output:** The dropdown shows "Groceries" selected immediately, without a page reload. Navigating away (to `/budget`) and back via the app's own links, then re-checking the dropdown, confirms the category stuck server-side — proves it actually called the real API, not just local UI state. (Not a browser reload: the access token is deliberately memory-only per `frontend-app.md`'s design, so a real page reload legitimately loses the session — that's an accepted tradeoff, not something this test should trip over.)

## Notes
- Reuses the existing `AuthContext`/API-client pattern from `frontend-app.md` — no new auth plumbing needed, `/transactions` is just another protected page like `/budget`.
- Category list for the dropdown comes from `GET /api/budget`'s `categories` array (already fetched data, no new endpoint needed) rather than a separate categories-list call — avoids adding an endpoint this slice doesn't otherwise need.

## Tests
- `frontend/e2e/transactions.spec.ts` § `"shows real seeded transaction data"` — covers § Transactions page shows real seeded data.
- `frontend/e2e/transactions.spec.ts` § `"changing category persists without a page reload"` — covers § Changing a transaction's category persists without a page reload.

Both confirmed red before commit — no `/transactions` route exists yet. Verified the existing `login-and-budget.spec.ts` suite is unaffected, including when both spec files run together in one invocation (this file's `beforeAll` seed only runs for its own tests; Playwright ran `login-and-budget.spec.ts` first). Known fragility: this ordering isn't explicitly enforced, just how Playwright currently orders a 2-file suite on 1 worker — if more e2e spec files get added later with their own seed side effects, revisit with explicit per-file isolation (e.g. `test.describe.serial` ordering or separate seeded users) rather than relying on file-name alphabetical luck.


## Changes
- 002 (2026-08-10) — initial contract, frontend counterpart to `transactions.md` within `changes/002-simplefin-and-transactions/plan.md`.
