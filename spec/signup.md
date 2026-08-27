---
status: built
depends_on: [auth.md]
---

# Signup: invite-only account creation

## Does
Adds self-serve account creation, gated by an operator-minted invite code.
This is the deliberate, separate decision that
`context/security-requirements.md` requires before reversing "no public
signup" — invite-only is the smallest reversal that keeps the demo
account's public-safety guarantee (signup never sets `is_demo`, codes are
minted only by the operator via `mint_invite.py`, demo-isolation tests are
untouched).

Also adds fixed-window rate limiting to `/api/login` and `/api/signup`.

## Done when
- With a valid, unused, unexpired invite code, a visitor can create an
  account (username + password, optional email) and is immediately logged
  in — same `{access_token}` body + refresh cookie as `/api/login`.
- An invite code is single-use: a second signup with the same code fails.
- The created user has `is_demo = False` and can subsequently log in via
  `/api/login`.
- Without a valid invite code, signup is refused — no account is created.
- Repeated failed logins from one client are throttled (`429`) rather than
  allowed to run unbounded.

## Integration test contract

### POST /api/signup

**Setup:** An `InviteCode` row exists with a known `code`, `used_at IS
NULL`, and either `expires_at IS NULL` or `expires_at` in the future. No
`User` exists with the chosen username (or email).
**Action:** `POST /api/signup`
**Input:** JSON body `{"username": "...", "password": "...", "invite_code":
"...", "email": "..."?}`. `email` is optional.
**Expected output:** `201`, JSON body `{"access_token": "<jwt>"}`. Access
token is response-body only, never a cookie (same as `/api/login`).
**Side effects:**
- A new `User` row: `username`, werkzeug `password_hash` (reuse existing
  hashing), `email` set iff supplied, `is_demo = False`.
- The `InviteCode` row is marked used: `used_at = now()`,
  `used_by_user_id = <new user id>`.
- One `RefreshToken` record created (hash stored, never the raw token),
  and a `Set-Cookie` for the refresh token: `HttpOnly; Secure;
  SameSite=Strict; Path=/api` — identical attributes to `/api/login`.

#### Error cases
- **When `username`, `password`, or `invite_code` is missing from the
  body, Then** `400`, no user created, invite code not consumed.
- **When `len(password) < 10` or `len(password) > 128`, Then** `400`, no
  user created, invite code not consumed.
- **When the invite code is unknown, already used, or past `expires_at`,
  Then** `403` with a single generic message
  (`"invalid or expired invite code"` — the three cases are
  indistinguishable in the response, so a probe can't tell "wrong code"
  from "used code"). No user created.
- **When `username` is already taken, Then** `409`. (Accepted tradeoff:
  signup inherently reveals whether a username is free; no attempt is
  made to hide it. The invite code is **not** consumed, so the visitor
  can retry with a different name.)
- **When `email` is supplied and already belongs to another user, Then**
  `409`. Invite code not consumed.
- **When the client has exceeded the signup rate limit, Then** `429`
  (optionally with `Retry-After`). Checked before the invite code, so a
  flood of guesses is throttled.

### Rate limiting (POST /api/login and POST /api/signup)

**Setup:** Any client (identified by IP — `request.remote_addr`, or the
`ProxyFix`-corrected address when `TRUSTED_PROXY_COUNT` is configured).
**Behavior:** A fixed-window counter per `(scope, ip)`:
- `login`: at most 10 attempts per rolling 15-minute window.
- `signup`: at most 5 attempts per rolling 60-minute window.
Requests beyond the limit return `429` without touching credentials, the
invite code, or the user table. Successful and failed attempts both count
(the point is to bound brute force). The window is a stored
`window_start` + `count`; when `now - window_start` exceeds the window
length the row resets.

#### Error cases
- **When the limit is exceeded, Then** `429`. Subsequent requests keep
  returning `429` until the window rolls over.

## Tests
- `tests/test_signup.py` — one test per contract line:
  - `test_signup_with_valid_invite_creates_user_and_logs_in` — 201,
    `access_token` in body, refresh cookie with the three attributes.
  - `test_signup_marks_invite_code_used` — `used_at` + `used_by_user_id`
    set after success.
  - `test_signup_created_user_is_not_demo` — `is_demo is False`.
  - `test_signup_created_user_can_then_log_in` — follow-up `/api/login`
    succeeds.
  - `test_signup_stores_email_when_supplied` / `_omits_email_when_not`.
  - `test_signup_missing_username_returns_400` /
    `_missing_password_returns_400` / `_missing_invite_code_returns_400`
    (and: invite code not consumed).
  - `test_signup_short_password_returns_400` /
    `_too_long_password_returns_400`.
  - `test_signup_unknown_invite_code_returns_403` /
    `_used_invite_code_returns_403` / `_expired_invite_code_returns_403` —
    all with the same generic message; no user created.
  - `test_signup_taken_username_returns_409` — invite code NOT consumed.
  - `test_signup_taken_email_returns_409`.
  - `test_signup_rate_limited_after_threshold_returns_429`.
  - `test_login_rate_limited_after_threshold_returns_429` — 10 bad logins
    then the 11th is `429` (lives here rather than `test_auth.py` because
    it's this slice's behavior; `test_auth.py` stays a pure `spec/auth.md`
    trace).

## Notes
- **Invite mechanism is a DB table, not a static allowlist.** An env
  allowlist needs a redeploy to rotate; an `InviteCode` row is
  single-use, revocable, and mintable via `mint_invite.py`
  (`python3 mint_invite.py [--expires-days N]`, prints a fresh
  `secrets.token_urlsafe` code). There is deliberately no HTTP endpoint
  that creates codes.
- **`User.email` added now, unused beyond storage.** Nullable + unique.
  Username remains the sole login identifier. Groundwork for a future
  password-reset slice so it needs no second `user` migration.
- **Password reset and email verification are out of scope** — separate
  follow-up. `security-requirements.md`'s OWASP-pass gate before a public
  production deploy still applies and is unaffected by this slice.
- **Rate limiting is deliberately coarse** — per-IP fixed window, no
  per-account lockout (avoids a lockout-as-DoS vector), no CAPTCHA. The
  `AuthThrottle` table is 2 real columns keyed by `(scope, key)`.
- **Client IP behind the proxy.** `context/tech-stack.md`'s deploy is
  k3s + a Tailscale ingress; `request.remote_addr` there is the ingress
  pod. `TRUSTED_PROXY_COUNT` (default `0`) gates
  `werkzeug.middleware.proxy_fix.ProxyFix(x_for=N)` in `app.py`. With the
  default, behavior is exactly today's `remote_addr`.
- **Mock boundary:** all real. Pure Postgres, same as `spec/auth.md`.
- **`is_demo` is never settable via signup** — the field isn't read from
  the request body at all. This is what keeps
  `security-requirements.md:11`'s demo guarantee intact.

## Changes
- 007 (2026-08-27) — contract created. Invite-only signup as the
  deliberate reversal of the "no public signup" line; `User.email` +
  `InviteCode` + `AuthThrottle` models; login + signup rate limiting.
- 007 (2026-08-27) — built. `models.py` (`User.email`, `InviteCode`,
  `AuthThrottle`); migration `33d384c0c915`; `auth_api.py` `signup` route +
  `_rate_limit_ok` (wired into `login` and `signup`) + `_validate_invite_code`;
  `app.py` `TRUSTED_PROXY_COUNT` + `ProxyFix`; `mint_invite.py`. Frontend:
  `client.ts` `register()`, `SignupPage.tsx`, `/signup` route, link from
  `LoginPage`. 21 tests in `tests/test_signup.py` + 3 e2e in
  `signup.spec.ts`. Full suite 149 passed / 9 Plaid-sandbox skipped;
  e2e 14 passed.
