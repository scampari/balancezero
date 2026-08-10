---
status: built
depends_on: []
---

# Auth: JWT login, refresh, logout

## Does
Replaces session-cookie auth with JWT access/refresh tokens, fixing the flagged session-revocation gap (see `context/security-requirements.md`), and establishes the protected-route pattern every other API slice will reuse.

## Done when
- A user can log in with username/password and receive an access token.
- The access token is required (and validated) on protected routes.
- A refresh token, issued alongside login, can mint a new access token without re-entering credentials.
- Logout actually revokes the refresh token server-side — a copied/replayed refresh cookie stops working immediately after logout, unlike the old Flask session cookie.

## Integration test contract

### POST /api/login

**Setup:** A `User` row exists with a known username and a werkzeug-hashed password (reuse existing hashing, don't redesign).
**Action:** `POST /api/login`
**Input:** JSON body `{"username": "...", "password": "..."}`
**Expected output:** `200`, JSON body `{"access_token": "<jwt>"}`. Access token is NOT set as a cookie — response body only, frontend holds it in memory.
**Side effects:** A new refresh-token record is created, associated with the user, storing a *hash* of the refresh token (never the raw token — same principle as password hashing, so a DB read alone can't yield a usable token). Response sets a `Set-Cookie` header for the refresh token: `HttpOnly; Secure; SameSite=Strict; Path=/api`. Path scoping is `/api` (the whole API surface), not narrower — `/api/login`, `/api/refresh`, `/api/logout` are flat sibling routes, and a cookie's `Path` attribute is a single prefix, not a set, so no `Path` value can include the latter two while excluding the first without renaming the routes. Accepted deviation from an earlier, more aspirational wording of this contract: `HttpOnly` already blocks JS access regardless of `Path`, and `/api/login` never reads the cookie, so the only real cost is an unused `Cookie` header on login requests.

#### Error cases
- **When password is wrong, Then** `401`, no access token issued, no refresh-token record created.
- **When username doesn't exist, Then** `401` with the *same* generic error message as wrong-password (avoid username enumeration via response differences).
- **When `username` or `password` is missing from the request body, Then** `400`.

### POST /api/refresh

**Setup:** A prior login produced a valid, unexpired, unrevoked refresh-token record, with its cookie available.
**Action:** `POST /api/refresh` (refresh cookie sent automatically by the browser; tests set it explicitly).
**Input:** No body required — refresh cookie is the credential.
**Expected output:** `200`, JSON `{"access_token": "<new jwt>"}`. `Set-Cookie` with a **new** refresh token (rotation).
**Side effects:** The old refresh-token record is revoked/deleted; a new one is created. The old refresh token cookie value must no longer work if reused (see reuse error case).

#### Error cases
- **When no refresh cookie is present, Then** `401`.
- **When the refresh token doesn't match any live record (revoked, already rotated-out, or never existed), Then** `401`.
- **When the refresh token is past its expiry, Then** `401`.

### POST /api/logout

**Setup:** A valid access token (Authorization header) and a valid refresh cookie from a prior login.
**Action:** `POST /api/logout`
**Input:** No body. Requires `Authorization: Bearer <access token>`.
**Expected output:** `200`. `Set-Cookie` clears the refresh cookie (`Max-Age=0`).
**Side effects:** The refresh-token record is revoked/deleted server-side. A subsequent `POST /api/refresh` using the old cookie must then fail with `401` — this is the actual fix for the old session-revocation gap; prove it in the test, don't just assert the 200.

#### Error cases
- **When called without a valid access token, Then** `401`.
- **When called with an already-revoked or missing refresh cookie, Then** still `200` (logout is idempotent — the end state "not logged in" is already true, so this isn't an error).

### Protected-route pattern (decorator/dependency, reused by future slices)

**Setup:** A valid, unexpired access token.
**Action:** Any request to a route wrapped with this pattern, `Authorization: Bearer <token>` header set.
**Expected output:** Request proceeds; the authenticated user is available to the route handler (equivalent to the old `session["user_id"]` pattern, but sourced from the validated token).
**Side effects:** None beyond normal request handling.

#### Error cases
- **When no `Authorization` header is present, Then** `401`.
- **When the token is malformed or has an invalid signature, Then** `401`.
- **When the token is expired, Then** `401` (client is expected to call `/api/refresh` and retry).

## Notes
- New schema: a `RefreshToken` (or similarly named) table — user_id, token hash, created_at, expires_at, revoked_at (nullable). First migration for this change; existing `User`/`Account`/`Category`/`Transaction`/`BudgetAllocation` models are unchanged.
- Refresh-token **reuse detection** (if a rotated-out/already-used refresh token is presented again — a signal of theft — proactively revoking *all* of that user's refresh tokens) is a real hardening measure worth doing for a financial app, but is **deferred past this walking-skeleton slice**, not silently dropped. Flag as a follow-up hardening spec once the basic flow is proven.
- CSRF: only `/api/refresh` and `/api/logout` touch the refresh cookie and need CSRF protection (e.g. origin check or double-submit token) — every other endpoint is bearer-token-only and needs none. See `context/security-requirements.md` for the full reasoning.
- Test database: real Postgres via Docker, not SQLite — decided during test-planning specifically so constraint/type behavior matches production.
- JWT library choice (flask-jwt-extended vs hand-rolled) is a build-time implementation detail, not part of this contract — the contract only specifies HTTP-observable behavior.

## Tests
- `tests/test_auth.py` § `"test_login_with_valid_credentials_returns_access_token_and_sets_refresh_cookie"` — covers § POST /api/login contract (happy path + cookie attributes).
- `tests/test_auth.py` § `"test_login_with_wrong_password_returns_401"` — covers § POST /api/login error case: wrong password.
- `tests/test_auth.py` § `"test_login_with_unknown_username_returns_401_with_same_message_as_wrong_password"` — covers § POST /api/login error case: unknown username, enumeration-safe.
- `tests/test_auth.py` § `"test_login_missing_username_returns_400"` — covers § POST /api/login error case: missing username.
- `tests/test_auth.py` § `"test_login_missing_password_returns_400"` — covers § POST /api/login error case: missing password.
- `tests/test_auth.py` § `"test_refresh_with_valid_cookie_returns_new_access_token_and_rotates_cookie"` — covers § POST /api/refresh contract (happy path + rotation).
- `tests/test_auth.py` § `"test_refresh_without_cookie_returns_401"` — covers § POST /api/refresh error case: no cookie.
- `tests/test_auth.py` § `"test_refresh_with_invalid_cookie_returns_401"` — covers § POST /api/refresh error case: unrecognized token.
- `tests/test_auth.py` § `"test_refresh_with_reused_rotated_out_cookie_returns_401"` — covers § POST /api/refresh error case: rotated-out token reuse.
- `tests/test_auth.py` § `"test_refresh_with_expired_token_returns_401"` — covers § POST /api/refresh error case: expired token.
- `tests/test_auth.py` § `"test_logout_revokes_refresh_token_so_subsequent_refresh_fails"` — covers § POST /api/logout contract, specifically the revocation proof (the actual security-gap fix).
- `tests/test_auth.py` § `"test_logout_without_access_token_returns_401"` — covers § POST /api/logout error case + protected-route pattern error case: missing Authorization header.
- `tests/test_auth.py` § `"test_logout_with_malformed_access_token_returns_401"` — covers § protected-route pattern error case: malformed/invalid signature.
- `tests/test_auth.py` § `"test_logout_with_expired_access_token_returns_401"` — covers § protected-route pattern error case: expired access token.
- `tests/test_auth.py` § `"test_logout_with_already_revoked_refresh_cookie_still_returns_200"` — covers § POST /api/logout error case: idempotent re-logout.
- `tests/test_auth.py` § `"test_logout_clears_refresh_cookie"` — covers § POST /api/logout contract, cookie-clearing side effect.

All 16 tests currently fail with 404 (no routes registered yet) — confirmed red for the right reason before commit.

## Changes
- 001 (2026-08-10) — initial contract, bootstrapped from `changes/001-api-spa-rewrite/plan.md`.
- 001 (2026-08-10) — built. V0a: `RefreshToken` model + migration. V0b: `auth_api.py` blueprint (login/refresh/logout), flask-jwt-extended for access tokens, custom error handlers normalizing all auth failures to 401 (library default was 422 for malformed tokens), CORS + CSRF-exemption wiring in `app.py`. All 16 tests green.
