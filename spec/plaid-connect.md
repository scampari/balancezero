---
status: built
depends_on: [auth.md]
---

# Plaid connect: Link token → access_token/item_id exchange

## Does
Lets the real (non-demo) user connect a bank account via Plaid Link:
backend mints a `link_token`, the frontend opens Plaid Link with it, the
user completes the flow, and the backend exchanges the resulting
`public_token` for a permanent `access_token` + `item_id`, storing the
access token encrypted at rest. Replaces `spec/simplefin-connect.md`
(superseded — see `changes/004-plaid-and-self-host/plan.md`).

## Done when
- A real user can request a `link_token`, complete Plaid Link (tests use
  `/sandbox/public_token/create` to skip the Link UI, per Notes), and have
  the resulting connection stored — encrypted, never the raw
  `access_token` sitting in a queryable column.
- The demo user can never connect a real bank (`is_demo` guard on both
  endpoints).
- A user can check whether they're currently connected, without the
  `access_token` ever appearing in a response once stored (write-only from
  the API's perspective, same as SimpleFIN's `/status`).
- Reconnecting (a second Link flow) replaces the stored connection, not an
  error.

## Integration test contract

### POST /api/plaid/link-token

**Setup:** An authenticated, non-demo user.
**Action:** `POST /api/plaid/link-token`, `Authorization: Bearer <access token>`.
**Input:** No body required — `client_user_id` for Plaid's `/link/token/create`
call is derived server-side from the JWT identity, not client-supplied.
**Expected output:** `200`, JSON `{"link_token": "<token>"}`.
**Side effects:** None (stateless call to Plaid's `/link/token/create`; no
DB write — nothing is persisted until `/connect` completes).

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When the authenticated user is the demo user, Then** `403` — demo
  accounts never see Plaid Link at all, not even the token-creation step.
- **When Plaid's `/link/token/create` call itself fails (bad
  `PLAID_CLIENT_ID`/`PLAID_SECRET`, Plaid outage), Then** `502`, sanitized
  generic error — same "never relay the provider's raw error" discipline
  as `simplefin-connect.md`.

### POST /api/plaid/connect

**Setup:** An authenticated, non-demo user with no existing connection. A
real `public_token` obtained via Plaid Sandbox's `/sandbox/public_token/create`
(real Sandbox call — see Notes on why this isn't mocked, unlike
`simplefin-connect.md`'s exchange).
**Action:** `POST /api/plaid/connect`, `Authorization: Bearer <access token>`.
**Input:** JSON `{"public_token": "<public_token>"}`.
**Expected output:** `200`, JSON `{"status": "connected"}`. Response never
includes `access_token` or `item_id`.
**Side effects:** Server calls Plaid's `/item/public_token/exchange` (real
Sandbox call), receives `access_token` + `item_id`, encrypts the
`access_token` (Fernet) and stores it on `User.plaid_access_token_encrypted`,
stores `item_id` plaintext on `User.plaid_item_id` (not a secret — see
`context/plaid-integration.md`). Confirmed via direct DB read in the test
that the stored `access_token` value is neither plaintext nor recognizably
related to it.

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When the authenticated user is the demo user, Then** `403`.
- **When `public_token` is missing from the request body, Then** `400`.
- **When Plaid rejects the exchange (invalid, expired, or
  already-exchanged `public_token`), Then** `502`, sanitized generic
  error — never relay Plaid's raw error body to the client.
- **When a connection already exists for this user, Then** the new
  exchange still succeeds and replaces the old encrypted value (`200`, not
  `409`) — same "reconnecting is legitimate" precedent as
  `simplefin-connect.md`.

### GET /api/plaid/status

**Setup:** An authenticated user, with or without an existing connection.
**Action:** `GET /api/plaid/status`, `Authorization: Bearer <access token>`.
**Expected output:** `200`, JSON `{"connected": true}` or
`{"connected": false}` depending on whether `plaid_access_token_encrypted`
is set. Never includes `access_token` or `item_id`.

#### Error cases
- **When no/invalid access token, Then** `401`.

## Tests
- `tests/test_plaid_connect.py` § `"test_link_token_created_for_authenticated_user"`
  — covers § POST /link-token contract.
- `tests/test_plaid_connect.py` § `"test_link_token_denied_for_demo_user"` —
  covers § POST /link-token error case: demo user.
- `tests/test_plaid_connect.py` § `"test_link_token_without_token_returns_401"`
  — covers § POST /link-token error case: no token.
- `tests/test_plaid_connect.py` § `"test_connect_with_valid_public_token_succeeds"`
  — covers § POST /connect contract (real Sandbox exchange).
- `tests/test_plaid_connect.py` § `"test_connect_without_token_returns_401"`
  — covers § POST /connect error case: no access token.
- `tests/test_plaid_connect.py` § `"test_connect_as_demo_user_returns_403"`
  — covers § POST /connect error case: demo user.
- `tests/test_plaid_connect.py` § `"test_connect_missing_public_token_returns_400"`
  — covers § POST /connect error case: missing field.
- `tests/test_plaid_connect.py` § `"test_connect_with_invalid_public_token_returns_502"`
  — covers § POST /connect error case: Plaid rejects exchange (sanitized).
- `tests/test_plaid_connect.py` § `"test_reconnect_replaces_existing_connection"`
  — covers § POST /connect contract: reconnecting replaces, doesn't conflict.
- `tests/test_plaid_connect.py` § `"test_status_returns_false_when_not_connected"`
  / `"test_status_returns_true_after_connecting"` — covers § GET /status contract.
- `tests/test_plaid_connect.py` § `"test_status_without_token_returns_401"` —
  covers § GET /status error case: no token.

9 of 12 confirmed red (404, no routes yet) before implementation — full
suite run (65 pre-existing tests, all still passing; 22.69s).

**Built.** After implementation: 58 passed, 4 skipped, 0 failed (full
suite). One test needed correcting during build:
`test_link_token_created_for_authenticated_user` was originally written
un-skipped (reasoning "no Plaid call needed to hit our own route") but a
`200` from the built route genuinely requires a real `/link/token/create`
call to Plaid — moved to `@requires_plaid_sandbox`, alongside the 3
already there (`test_connect_with_valid_public_token_succeeds`,
`test_reconnect_replaces_existing_connection`,
`test_status_returns_true_after_connecting`).

**Fully verified.** Real `PLAID_CLIENT_ID`/`PLAID_SECRET` Sandbox
credentials became available after build — all 12 tests pass for real
against live Plaid Sandbox (12 passed, 0 skipped, 0 failed). The
`@requires_plaid_sandbox` skip condition remains in the test file for
future environments (CI, a fresh clone) that don't have Sandbox
credentials set — it's not dead code, just not currently exercised.

## Notes
- Created by auto-plan-grill from `changes/004-plaid-and-self-host/plan.md`
  — read that plan's `## Grill` and `open-questions.md` before writing the
  contract. Two endpoints, not one: `POST /api/plaid/link-token` then
  `POST /api/plaid/connect` — Plaid's flow requires minting a `link_token`
  before Link can open, unlike SimpleFIN's single-call exchange.
- Requires a migration: rename `User.simplefin_access_url_encrypted` →
  `plaid_access_token_encrypted`, add `User.plaid_item_id`, rename
  `Account.simplefin_account_id` → `plaid_account_id` (also adding the
  `UniqueConstraint("user_id", "plaid_account_id")` that was already
  missing before), rename `Transaction.simplefin_transaction_id` →
  `plaid_transaction_id`. No data-preserving path from the old column —
  see plan's Grill, "Real SimpleFIN connection may already exist locally."
- New required env vars: `PLAID_CLIENT_ID`, `PLAID_SECRET`,
  `PLAID_ENCRYPTION_KEY` (replaces `SIMPLEFIN_ENCRYPTION_KEY`). No
  default/fallback on the encryption key, same discipline as before.
- **Resolved (verified against current Plaid docs, 2026-08-26): "Sandbox
  OAuth-institution coverage" open question.** Plaid Sandbox uses "a single
  generic OAuth flow rather than institution-specific OAuth behavior," and
  accepts `http://localhost` redirect URIs in Sandbox (Production requires
  `https`). This slice does NOT need `spec/self-hosted-deploy.md`'s real
  hostname to exist first — a localhost placeholder redirect URI is
  sufficient for Sandbox testing. Confidence raised from medium to high;
  removed from `open-questions.md`.
- **Mock boundary, resolved: real Plaid Sandbox calls, NOT mocked.**
  Different from `simplefin-connect.md`'s precedent. SimpleFIN's demo
  bridge exchange turned out to be a one-time-claim resource that got
  exhausted after a handful of real test reruns (see that spec's Notes) —
  Plaid Sandbox is explicitly built for the opposite: "create an unlimited
  number of test Items," default credentials (`user_good`/`pass_good`)
  work repeatedly, and `/sandbox/public_token/create` generates a fresh
  `public_token` programmatically (bypassing the Link UI/browser entirely)
  for exactly this use case. Per `context/testing.md`'s mock-boundary
  table, this is the "uncontrolled WITH a reliably repeatable test
  environment" case → real calls, nothing mocked. Promoted to
  `context/testing.md`.
- **No SSRF surface here, unlike SimpleFIN's `/connect`.** SimpleFIN's
  four security-review findings (SSRF, redirect bypass, unbounded body,
  unvalidated shape) were all consequences of the claim URL being
  user-supplied (decoded from the client's setup token) — the app called
  wherever that token pointed. Plaid's flow never does this: `link-token`
  and `connect` always call a fixed, hardcoded Plaid API host
  (`sandbox.plaid.com` / `production.plaid.com` depending on environment),
  never a client-supplied URL. `public_token` is an opaque string, not a
  URL. Don't carry the SimpleFIN slice's SSRF-defense checklist into this
  slice's security review by default — the threat model is different. Use
  Plaid's official Python SDK (handles TLS/host correctly) rather than
  raw `requests` calls to an arbitrary host.
- Frontend needs the `react-plaid-link` package — not present in
  `frontend/package.json` today. Frontend work itself is out of scope for
  this spec's backend contract but the dependency should be flagged when
  build starts.

## Changes
- 004 (2026-08-26) — integration test contract landed by auto-test-planning.
  Mock boundary resolved (real Sandbox, not mocked — see Notes); Sandbox
  OAuth-institution open question resolved (no dependency on
  self-hosted-deploy.md). High confidence throughout — proceeding to
  auto-test-writer.
- 004 (2026-08-26) — 12 tests written (`tests/test_plaid_connect.py`), 9
  confirmed red, 3 skipped pending real Plaid Sandbox credentials in this
  environment. `plaid-python` added to `requirements.txt`.
- 004 (2026-08-26) — built. `plaid_api.py` implements all three routes;
  migration `69650ded897a` renames the SimpleFIN-era columns and adds
  `plaid_item_id` + the `Account` unique constraint. `simplefin_api.py` and
  its tests removed (superseded, dead code once the blueprint was
  unregistered). 58 passed, 4 skipped, 0 failed (full suite) — a 4th test
  needed moving to `@requires_plaid_sandbox` during build, see Notes above.
  `app.py`, `conftest.py`, `dev.sh` updated for the new env vars
  (`PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENCRYPTION_KEY`).
- 2026-08-27 — frontend Link flow wired (the piece flagged out-of-scope in
  Notes). `react-plaid-link` added to `frontend/package.json`; `client.ts`
  gains `createPlaidLinkToken` / `connectPlaid` (+ auto-refresh wrappers);
  new `frontend/src/components/ConnectBankButton.tsx` runs the two-step
  flow via `usePlaidLink`; `AccountsPage` shows "Connect a bank" (or
  "Reconnect bank" once connected), gates "Sync now" on connection status
  from `/api/plaid/status`, and auto-syncs after a successful connect.
  Verified end-to-end against the running app: the button calls
  `POST /api/plaid/link-token` and surfaces the backend's `403` for the
  demo user inline. A real-bank Sandbox click-through still needs real
  `PLAID_CLIENT_ID`/`PLAID_SECRET` in the environment.
- 2026-08-27 — OAuth-institution redirect wired (some banks require it).
  Backend: new optional `PLAID_REDIRECT_URI` config (`app.py`), passed to
  `link_token_create` only when set (`plaid_api.py`) — Plaid rejects an
  unregistered redirect_uri, so it must be omitted otherwise. Frontend:
  `ConnectBankButton` parks the `link_token` in `localStorage` across the
  full-page OAuth redirect (documented Plaid guidance; scoped to one key,
  deleted on flow end — a deliberate, narrow exception to
  `context/security-requirements.md`'s "no tokens in web storage", which
  targets the JWT/refresh token, not the short-lived single-institution
  `link_token`), then re-inits Link with `receivedRedirectUri` and
  auto-opens when it lands back on `/accounts?oauth_state_id=...`. Also
  added `python-dotenv` + `load_dotenv()` so a gitignored project-root
  `.env` supplies these (`requirements.txt`, `app.py`, `dev.sh`).
  Operator must register the redirect URI in the Plaid dashboard (Team
  Settings → API → Allowed redirect URIs). Target is Production
  (`PLAID_ENV=production`, Production `PLAID_SECRET`, Link use case set
  under Data Transparency): redirect URI
  `https://balancezero.<tailnet>.ts.net/accounts` — Production requires
  `https://`, so a local production build needs a self-signed https origin
  or must point at the deployed host. Sandbox would use
  `http://localhost:5173/accounts`. Non-OAuth linking is unaffected when
  `PLAID_REDIRECT_URI` is unset. Full backend suite green (128 passed, 9
  Plaid-sandbox skips).
