---
status: planned
depends_on: [auth.md]
---

# SimpleFIN connect: Setup Token → encrypted Access URL

## Does
Lets the real (non-demo) user connect a SimpleFIN Bridge account: paste a Setup Token, the server exchanges it for an Access URL and stores it encrypted at rest (SimpleFIN's own stated requirement — see `context/simplefin-integration.md`). This is what `simplefin-sync.md` will use to actually pull transactions in the next slice.

## Done when
- A real user can submit a Setup Token and, if valid, have their SimpleFIN connection stored — encrypted, never the raw Access URL sitting in a queryable column.
- The demo user can never connect a real bank (`is_demo` guard) — the two-user isolation design depends on the demo account never touching a real external service.
- A user can check whether they're currently connected, without ever seeing the Access URL itself again once it's stored (write-only from the API's perspective).
- Manually verified against SimpleFIN's real public demo token before writing any code (see Notes) — but the automated test suite mocks the exchange itself; see Notes for why.

## Integration test contract

### POST /api/simplefin/connect

**Setup:** An authenticated, non-demo user with no existing connection.
**Action:** `POST /api/simplefin/connect`, `Authorization: Bearer <access token>`.
**Input:** JSON `{"setup_token": "<base64-encoded claim URL>"}`. Tests use SimpleFIN's public demo token (`aHR0cHM6Ly9iZXRhLWJyaWRnZS5zaW1wbGVmaW4ub3JnL3NpbXBsZWZpbi9jbGFpbS9ERU1PLXYyLUE4MEVDOUI5NDlGMjQxOEE0QzhE`, decodes to `https://beta-bridge.simplefin.org/simplefin/claim/DEMO-v2-A80EC9B949F2418A4C8D`) as the realistic *shape* of the value, but the actual outbound exchange is mocked in tests — see Notes.
**Expected output:** `200`, JSON `{"status": "connected"}`. Response never includes the Access URL or any part of it.
**Side effects:** Server base64-decodes the setup token to a claim URL, `POST`s to it (no body), receives the real Access URL as a `text/plain` response body, encrypts it (Fernet), and stores it on `User.simplefin_access_url_encrypted`. Confirmed via direct DB read in the test that the stored value is neither the plaintext Access URL nor recognizably related to it (i.e., actually encrypted, not just base64'd again).

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When the authenticated user is the demo user (`is_demo=True`), Then** `403` — demo accounts never connect real banks.
- **When `setup_token` is missing from the request body, Then** `400`.
- **When `setup_token` isn't valid base64, or decodes to something that isn't an `https://` URL, Then** `400` (defense against a malformed/malicious token attempting to make the server POST to an arbitrary or non-HTTPS internal address).
- **When the decoded claim URL rejects the exchange (SimpleFIN returns a non-2xx), Then** `502`, with a generic, sanitized error message — never relay SimpleFIN's raw response body back to the client (per `context/simplefin-integration.md`'s "sanitize error messages" requirement).
- **When a connection already exists for this user, Then** the new exchange still succeeds and replaces the old encrypted value (`200`, not `409`) — reconnecting is a legitimate action (e.g. after revoking access on SimpleFIN's side), not an error.

### GET /api/simplefin/status

**Setup:** An authenticated user, with or without an existing connection.
**Action:** `GET /api/simplefin/status`, `Authorization: Bearer <access token>`.
**Expected output:** `200`, JSON `{"connected": true}` or `{"connected": false}` depending on whether `simplefin_access_url_encrypted` is set. Never includes the Access URL itself, encrypted or not.

#### Error cases
- **When no/invalid access token, Then** `401`.

## Notes
- Encryption key: a new required env var, `SIMPLEFIN_ENCRYPTION_KEY` (a Fernet key — `cryptography.fernet.Fernet.generate_key()`). No default/fallback — failing loudly if it's unset is correct here, not a UX nicety to soften; this is the key protecting real bank-access credentials.
- `models.py`'s existing comment on `simplefin_access_url_encrypted` already anticipated Fernet ciphertext (`LargeBinary` column) — no schema change needed, just the first thing that actually writes to it.
- Uses `requests` for the outbound POST to the claim URL — added as a new dependency (Flask's own dependency tree doesn't include an HTTP *client*, only server-side routing).
- Rate limits (24 req/day) don't apply to this endpoint — that's `simplefin-sync.md`'s concern, once `/accounts` is being polled repeatedly. A single one-time claim-URL exchange is negligible by comparison.
- **Mock-boundary correction, made during this slice's own development**: this contract originally planned to hit SimpleFIN's real demo bridge in every automated test run, treating it as a Stripe-test-mode-style "safe, reusable test environment." That assumption was wrong. Manual verification (`curl -X POST` against the decoded claim URL) succeeded twice, then a handful of real test runs during development exhausted it — the bridge started returning `403 Forbidden (was it already claimed?)`, and it didn't recover after waiting. The demo token's "reusable" documentation apparently means something narrower than "safe to re-exchange indefinitely across an automated test suite's many reruns." Corrected: the outbound `requests.post` call is now mocked at the HTTP client layer (`unittest.mock.patch("simplefin_api.requests.post", ...)`), which is the documented fallback category in `context/testing.md`'s mock-boundary table for "uncontrolled, no *reliably repeatable* safe test environment" — everything except that one network call (decoding, validation, encryption, DB writes, error handling) still runs for real.

## Tests
- `tests/test_simplefin_connect.py` § `"test_connect_with_valid_token_succeeds"` — covers § POST /connect contract (exchange mocked, everything else real).
- `tests/test_simplefin_connect.py` § `"test_connect_without_token_returns_401"` — covers § POST error case: no access token.
- `tests/test_simplefin_connect.py` § `"test_connect_as_demo_user_returns_403"` — covers § POST error case: demo user.
- `tests/test_simplefin_connect.py` § `"test_connect_missing_setup_token_returns_400"` — covers § POST error case: missing field.
- `tests/test_simplefin_connect.py` § `"test_connect_invalid_base64_returns_400"` — covers § POST error case: invalid base64.
- `tests/test_simplefin_connect.py` § `"test_connect_non_https_decoded_url_returns_400"` — covers § POST error case: non-https decoded URL.
- `tests/test_simplefin_connect.py` § `"test_connect_with_bad_claim_url_returns_502"` — covers § POST error case: exchange rejected, sanitized error.
- `tests/test_simplefin_connect.py` § `"test_reconnect_replaces_existing_connection"` — covers § POST contract: reconnecting replaces, doesn't conflict.
- `tests/test_simplefin_connect.py` § `"test_status_returns_false_when_not_connected"` / `"test_status_returns_true_after_connecting"` — covers § GET /status contract.
- `tests/test_simplefin_connect.py` § `"test_status_without_token_returns_401"` — covers § GET error case: no token.

All 11 confirmed red (404, no routes yet) before commit. No external network dependency — verified reliable across 3 consecutive full reruns after the mock-boundary correction (see Notes).

## Changes
- 002 (2026-08-10) — initial contract, within `changes/002-simplefin-and-transactions/plan.md`.
