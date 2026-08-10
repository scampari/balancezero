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

## Changes
- 001 (2026-08-10) — initial contract, third slice of `changes/001-api-spa-rewrite/plan.md`.
- 001 (2026-08-10) — built. Real React app (api client, auth context, login/budget pages, router). All 4 e2e tests green against the real Flask backend and real browser. Full backend suite (36 tests) unaffected.
- 002 (2026-08-10) — added silent-refresh-on-mount: AuthProvider now attempts one `/api/refresh` call on load, gated behind a new `isAuthChecked` flag pages wait for before redirecting to login. Found and fixed a real React StrictMode-exposed bug during this: without a ref guard, StrictMode's dev-only double-invoke fired two concurrent refresh calls racing against the same one-time-use rotating cookie — one 200s, one 401s, and the wrong one could win. All 7 e2e tests green (3 reruns for stability), full 50-test backend suite unaffected.
