---
status: built
depends_on: [auth.md, budget-api.md]
---

# Frontend app: React SPA shell — login + budget page

## Does
The walking skeleton for the new frontend: a Vite + TypeScript + React Router app that logs in against the real `/api/login` endpoint, holds the access token in memory (per `context/security-requirements.md`), and renders the real budget view from `/api/budget`. Proves the whole new architecture (React SPA talking to the Flask JSON API over real HTTP, with real JWT auth) works end-to-end on the smallest real page, before any richer UI work happens on top of it.

## Done when
- A user can visit the app, log in with real credentials, and land on a budget page showing real data fetched from the real Flask API.
- Wrong credentials show an error and don't navigate away from login.
- Visiting the budget page without being logged in redirects to login (route guard) rather than showing an empty/broken page.
- Access token is held in memory only (a React context, not localStorage) — verified by the e2e test never finding it in any browser storage.

## Integration test contract

Tests are Playwright e2e tests driving a real browser against the real Flask backend (test Postgres via the existing `docker-compose.yml` service) and the real Vite dev server — not a mocked API. This matches the mock-boundary default already established for this project's backend tests (`context/testing.md`): prefer real dependencies over mocks wherever practical.

### Login → budget page (happy path)

**Setup:** A real test user exists in the test database (seeded via a script before the Playwright suite runs, same pattern as `seed_test_user.py`), with no categories/allocations yet (fresh state).
**Action:** Navigate to `/login`, fill in the test user's username and password, submit.
**Expected output:** Navigates to `/budget`. Page shows "Ready to Assign: $0.00" (no income yet) and an empty categories list — real values from the real `/api/budget` response, not hardcoded.
**Side effects:** None beyond the real `/api/login` call issuing a real access token + refresh cookie.

### Login with wrong password

**Setup:** Same test user.
**Action:** Navigate to `/login`, submit with the correct username but wrong password.
**Expected output:** Stays on `/login`, shows a visible error message. No navigation to `/budget`.

### Unauthenticated visit to /budget redirects to /login

**Setup:** A fresh browser context — no prior login, no cookies.
**Action:** Navigate directly to `/budget`.
**Expected output:** Redirected to `/login` (route guard), not a blank or broken page.

### Access token is never persisted to browser storage

**Setup:** Complete a real login (as in the happy-path test).
**Action:** After landing on `/budget`, inspect `localStorage` and `sessionStorage` in the browser context.
**Expected output:** Neither contains the access token (or anything that looks like a JWT) — it must exist only in React state/memory, per the token-storage decision in `context/security-requirements.md`.

### Reloading the page restores the session via the refresh cookie

**Setup:** Complete a real login (valid refresh cookie now set).
**Action:** Perform a real browser reload (`page.reload()`, not client-side navigation) while on `/budget`.
**Expected output:** Stays on `/budget` showing real data — not redirected to `/login`. The in-memory access token is gone after a reload (that's expected, nothing persists it), but the app must attempt one silent `/api/refresh` on load using the still-valid httpOnly cookie before concluding the user is logged out, rather than redirecting immediately just because `accessToken` starts `null`.

#### Error case
- **When there's no valid refresh cookie (fresh context, never logged in), Then** the silent-refresh attempt fails and the user is redirected to `/login` as before — this case is already covered by "Unauthenticated visit to /budget redirects to /login," just confirming the new mount-time check doesn't change that outcome, only adds a check before it.

## Notes
- Frontend lives in a new `frontend/` directory: Vite + TypeScript + React Router, `frontend/src/api/client.ts` for the typed API client, `frontend/src/auth/AuthContext.tsx` for the in-memory access-token store, `frontend/src/pages/LoginPage.tsx` and `BudgetPage.tsx`.
- On a 401 from any API call (expired access token), the client should transparently call `/api/refresh` once and retry — this isn't a separately listed contract case above since it's UI plumbing, not a distinct user-visible behavior, but it should work given `auth.md`'s refresh endpoint already exists and is tested.
- This slice is deliberately minimal per the plan: login + budget view only. Category creation and allocation UI (both already have working API endpoints from `budget-api.md`) are follow-up work, not part of this walking skeleton.
- Playwright's browser binaries need to be installed (`npx playwright install`) — a one-time setup step, not part of `npm install`.

## Tests
- `frontend/e2e/login-and-budget.spec.ts` § `"logging in with valid credentials shows the real budget page"` — covers § Login → budget page (happy path).
- `frontend/e2e/login-and-budget.spec.ts` § `"wrong password shows an error and stays on the login page"` — covers § Login with wrong password.
- `frontend/e2e/login-and-budget.spec.ts` § `"visiting /budget while logged out redirects to /login"` — covers § Unauthenticated visit to /budget redirects to /login.
- `frontend/e2e/login-and-budget.spec.ts` § `"access token is never written to localStorage or sessionStorage"` — covers § Access token is never persisted to browser storage.
- `frontend/e2e/login-and-budget.spec.ts` § `"reloading the page restores the session via the refresh cookie"` — covers § Reloading the page restores the session via the refresh cookie. Added 2026-08-10, after discovering during `transactions-ui.md`'s build that a real reload always bounced to `/login` even with a valid session — confirmed red before this fix.

All 4 confirmed red before commit — no login form or routing exists yet. The e2e harness itself (Docker test-db reset via `seed_e2e.py`, real Flask server, real Vite dev server via proxy, real Chromium browser) is fully working; only the React app is missing.

## Theme selection (changes/010)

The app ships several themes, chosen from a `<select aria-label="Theme">` in
the `AppShell` header:

- **Options:** `System` (default), `Light`, `Dark`, `Dark dim`, `Dark ocean`.
  `System` follows the OS `prefers-color-scheme` live (tracks changes while
  selected). The default dark palette is a calm, low-saturation indigo —
  replacing the original high-saturation emerald.
- **Persistence:** the raw choice is saved to `localStorage['bz.theme']` and
  reapplied on next load. A `<head>` script in `index.html` sets
  `data-theme` + `color-scheme` on `<html>` before first paint (no flash);
  `frontend/src/theme/ThemeContext.tsx` takes over once React mounts.
  `localStorage` is appropriate here — a theme is a display preference, not a
  credential (contrast the access-token rule in
  `context/security-requirements.md`).
- **Light mode is real** — every component reads `--color-*` tokens, and
  `index.css` defines a full light palette (including `--color-on-accent`
  for text on accent fills, and higher-alpha `--color-accent-bg` /
  `--color-accent-border` so tints and focus rings stay visible on white).
  `color-scheme: light` is set so native controls match.
- **Not asserted by e2e:** exact colors. `frontend/e2e/theme.spec.ts`
  checks the picker exists, that choosing Light sets
  `html[data-theme="light"]` and survives a reload, and that `System`
  tracks `emulateMedia({ colorScheme })`.

## Overspend notification + Cover dialog (changes/030)

The budget page tells the user when an envelope has gone negative and lets them fix it in place, without leaving the page or hand-editing two allocation inputs.
The user-facing verb is **cover** (see `context/budget-glossary.md`); the API call behind it is `POST /api/allocations/move` in `spec/budget-api.md`.

**Which categories count as overspent:** an entry in `GET /api/budget`'s `categories` with `available < 0`, `is_group` false.
Groups are excluded because they are not allocatable — a group alert would carry a button with nothing to do.
Archived categories are excluded because they are already out of `categories`.
No new API field: the page derives this from the budget it already fetches.

### Integration test contract

Playwright e2e against the real Flask backend and real Vite dev server, same harness as the tests above.

#### The banner appears and names each overspent envelope

**Setup:** Seeded logged-in user viewing the current month with two leaf categories — "Groceries" overspent (`available` negative) and "Dining" holding a positive balance at least as large.
**Action:** Load `/budget`.
**Input:** None.
**Expected output:** A banner is visible above the category table, named as an alert region, stating how many envelopes are overspent and listing "Groceries" with its negative amount. Each listed envelope has a **Cover** button.
**Side effects:** None.

#### The banner is absent when nothing is overspent

**Setup:** Same user, every category at zero or positive `available`.
**Action:** Load `/budget`.
**Expected output:** No banner. No Cover button anywhere on the page.
**Side effects:** None.

#### Covering from another envelope clears the banner

**Setup:** The overspent state from the first case — Groceries at `-40.00`, Dining at `+100.00`.
**Action:** Click **Cover** on the Groceries row of the banner, pick "Dining" as the source, accept the pre-filled amount, submit.
**Input:** Source "Dining", amount `40.00`.
**Expected output:** The dialog closes. The banner disappears. Groceries' `available` reads `$0.00` and is no longer red; Dining's reads `$60.00`. Ready to Assign is unchanged from before the move.
**Side effects:** Two `BudgetAllocation` rows written for the viewed month — Groceries `+40.00`, Dining `−40.00` against their prior values. Surviving a page reload proves it was persisted, not just local state.

#### Covering from Ready to Assign

**Setup:** Groceries overspent by `40.00`; Ready to Assign is `100.00`.
**Action:** Click **Cover**, leave the source on its default "Ready to Assign", submit `40.00`.
**Expected output:** Banner clears, Groceries reads `$0.00`, Ready to Assign now reads `$60.00`.
**Side effects:** One `BudgetAllocation` row written (Groceries `+40.00`). No other category changes.

#### The dialog pre-fills the amount needed

**Setup:** Groceries overspent by `37.50`.
**Action:** Click **Cover** on the Groceries row.
**Expected output:** The amount field already contains `37.50` — the exact figure that brings the envelope to zero. The destination is fixed to Groceries and is not editable from this entry point.
**Side effects:** None.

#### Error case: source does not hold enough

**Setup:** Groceries overspent by `40.00`; Dining holds only `10.00`.
**Action:** Click **Cover**, pick "Dining", submit `40.00`.
**Expected output:** The dialog stays open and shows an inline error saying the source does not have that much. The banner is still there and no amounts on the page have changed. Reloading confirms nothing was written.
**Side effects:** None — the backend rejects with `400` and writes no rows, so a move can never leave the two envelopes out of balance.

### Notes
- The source picker offers only leaf, non-archived categories with `available > 0`, plus "Ready to Assign" when that figure is positive. Offering a source that cannot fund the move would only produce the error above.
- Covering an envelope back to exactly zero is the expected outcome, not overfunding it. The pre-filled amount reflects that; the user may still type a larger one.
- Not asserted by e2e: banner styling and dialog layout. The contract covers presence, contents, and the numbers after the move.

## Changes
- 001 (2026-08-10) — initial contract, third slice of `changes/001-api-spa-rewrite/plan.md`.
- 001 (2026-08-10) — built. Real React app (api client, auth context, login/budget pages, router). All 4 e2e tests green against the real Flask backend and real browser. Full backend suite (36 tests) unaffected.
- 002 (2026-08-10) — added silent-refresh-on-mount: AuthProvider now attempts one `/api/refresh` call on load, gated behind a new `isAuthChecked` flag pages wait for before redirecting to login. Found and fixed a real React StrictMode-exposed bug during this: without a ref guard, StrictMode's dev-only double-invoke fired two concurrent refresh calls racing against the same one-time-use rotating cookie — one 200s, one 401s, and the wrong one could win. All 7 e2e tests green (3 reruns for stability), full 50-test backend suite unaffected.
- 030 (2026-09-08) — overspend notification + Cover dialog (contract
  above). `BudgetPage.tsx` gains a banner listing overspent leaf
  categories and a Cover dialog that calls the new `POST
  /api/allocations/move`; `client.ts` gains `moveAllocation` +
  `moveAllocationWithAutoRefresh`. No new API field — overspent is
  derived from the budget the page already fetches.
  `changes/030-overspend-cover/plan.md`.
