# Slicing: invite-only signup + login

> Date: 2026-08-27
> Status: built
> Branch: changes/007-invite-only-signup

## What & Why
BalanceZero has no self-serve account creation — users are made with
repo-root `seed_*.py` scripts. The user wants a real signup flow. Open
public registration is deliberately excluded by
`context/security-requirements.md:3` ("no public signup, no arbitrary
strangers... do not add open registration without a deliberate, separate
decision") and the public demo account's safety guarantee rests on the
two-user design (`:11`).

This slice is that deliberate, separate decision, taken at the smallest
scope that keeps the guarantee: **invite-only signup**. A `/signup` page
gated by an operator-minted invite code. Signup never sets `is_demo`, so
demo isolation and its tests are untouched.

## Spec changes
- `spec/signup.md` — created — `POST /api/signup` contract: invite-code
  gate, username/password/optional-email, `201` + access token + refresh
  cookie (same shape as `/api/login`), full 400/403/409/429 matrix. A
  rate-limit section covering **both** `/api/login` and `/api/signup`.
- `spec/auth.md` — modified — Notes: `/api/login` now also rate-limited
  (fixed-window per IP); behavior contract unchanged otherwise. Status
  stays `built`.

## Context changes
- `context/security-requirements.md` — new bullet: invite-only signup is
  the deliberate reversal of the "no public signup" line. Guarantee
  preserved because signup never sets `is_demo`, invite codes are
  operator-minted (no self-serve code generation), and demo-isolation
  tests are unchanged. Password reset + email verification are explicitly
  deferred.

## Constraints
- **Invite codes are a DB table (`InviteCode`), not a static env
  allowlist.** Single-use (`used_at` / `used_by_user_id`), optionally
  expiring (`expires_at`), mintable/revocable without a redeploy. Codes
  are created **only** by the operator via a new repo-root
  `mint_invite.py` CLI — there is no HTTP path that generates a code.
- **`User.email` is added now** (`String(255)`, `nullable=True`, unique),
  so a future password-reset slice needs no second `user` migration.
  Username stays the login identifier — `/api/login` is byte-for-byte
  unchanged. Email is captured at signup only when supplied. **No email
  sending or verification in this slice.**
- **Rate limiting is a DB fixed-window counter (`AuthThrottle`), no new
  dependency.** `UniqueConstraint("scope", "key")`; `scope` is
  `"login"` / `"signup"`, `key` is the client IP. Thresholds: login
  10 / 15 min, signup 5 / 60 min → `429`. The login threshold stays ≥10
  so no existing `tests/test_auth.py` test (each gets a fresh table, none
  makes >2 login calls) trips it.
  - Client IP: behind the k3s/Tailscale ingress `request.remote_addr` is
    the proxy. New optional `TRUSTED_PROXY_COUNT` config (default `0`) +
    `werkzeug.middleware.proxy_fix.ProxyFix` applied when it's set. Local
    dev and tests use `remote_addr` directly.
- **Password strength: length only** — `10 <= len(password) <= 128`
  server-side (upper bound guards the hash cost). Keep
  `werkzeug.security.generate_password_hash` (matches `conftest.py` and
  every existing user).
- **On success, log the new user straight in** — mint an access token +
  refresh cookie exactly as `login()` does (reuse `_issue_refresh_token`,
  `_set_refresh_cookie`). No separate "now log in" step.
- **Username enumeration on `409`** (username taken) is accepted and
  documented — signup inherently reveals whether a name is free.

## Non-Goals
- No open / public registration. No CAPTCHA. No email verification. No
  password reset (separate follow-up slice — noted in `spec/signup.md`).
- No password-complexity rules beyond length. No `zxcvbn`.
- No invite-code management UI or API — `mint_invite.py` only.
- No account lifecycle fields (`is_active`, roles, etc.).
- No change to `/api/login` / `/api/refresh` / `/api/logout` behavior
  beyond adding the login rate limit.

## Build skills
- None new — same Flask + SQLAlchemy + flask-jwt-extended + pytest stack,
  same werkzeug hashing and blueprint patterns already in `auth_api.py`.

## Slices
- **007-A** backend — `models.py` (`User.email`, `InviteCode`,
  `AuthThrottle`) + migration + `auth_api.py` (`signup` route, throttle
  helper wired into `login` + `signup`, invite validation) +
  `mint_invite.py`. `spec/signup.md` contract + `tests/test_signup.py`.
- **007-B** frontend — `client.ts` `register()`, `SignupPage.tsx`,
  `/signup` route in `App.tsx`, link from `LoginPage.tsx`. e2e
  `signup.spec.ts` + `seed_e2e_signup.py`.

## Verification
- `venv/bin/pytest` full suite green (baseline ≈128 passed / 9 skipped);
  new `tests/test_signup.py` green; existing `tests/test_auth.py`
  unaffected by the throttle.
- Migration `flask db upgrade` → `downgrade -1` → `upgrade` clean.
- `cd frontend && npm run build && npm run lint` clean.
- `npm run test:e2e` full suite green including the new spec.
- Manual: `python3 mint_invite.py` → `/signup` with the code → land
  `/budget`; reuse the code → fails; ~10 rapid bad logins → `429`; demo
  login still works.
