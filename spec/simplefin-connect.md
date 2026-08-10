---
status: built
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
- **When `setup_token` isn't valid base64, decodes to something that isn't an `https://` URL, or decodes to an `https://` URL on a host outside SimpleFIN Bridge's known domains (`bridge.simplefin.org`, `beta-bridge.simplefin.org`), Then** `400` — the scheme check alone doesn't stop a token aimed at an internal or third-party host (found during this slice's own security review; see Notes).
- **When the decoded claim URL rejects the exchange (SimpleFIN returns anything other than exactly `200`), Then** `502`, with a generic, sanitized error message — never relay SimpleFIN's raw response body back to the client (per `context/simplefin-integration.md`'s "sanitize error messages" requirement). Redirects are treated as a failure, not followed (see Notes — a compromised claim endpoint could otherwise redirect around the domain allowlist).
- **When the claim response body exceeds a size cap, or doesn't look like an `https://user:pass@host/...` access URL, Then** `502` — nothing is stored (see Notes).
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
- **Security review findings, fixed before this slice was marked built**: the plan flagged this slice for a focused security pass (real bank-access credentials). A dedicated review surfaced four real issues, all fixed:
  1. **SSRF via the claim URL** — the original `https://` scheme check didn't restrict the *host*, so an authenticated user could submit a token decoding to `https://169.254.169.254/...` or any other internal https-enabled address, turning the app server into an SSRF pivot. Fixed with a host allowlist (`bridge.simplefin.org`, `beta-bridge.simplefin.org`).
  2. **Redirect bypass** — `requests` follows redirects by default, which would let a compromised claim endpoint 302 the request around the domain allowlist entirely. Fixed with `allow_redirects=False`; anything other than a direct `200` is treated as a failure.
  3. **Unbounded response body** — the exchange response was read into memory with no size limit, a memory-exhaustion DoS vector via a malicious/compromised endpoint. Fixed with a 4KB cap via streamed reads (real access URLs are a few hundred bytes).
  4. **No shape validation on the stored value** — the raw response body was encrypted and stored verbatim with no check that it actually looked like an access URL, meaning a malicious response could poison the stored credential with something `simplefin-sync.md` would later decrypt and feed to an HTTP client unexamined. Fixed with a `_looks_like_access_url` check (`https://user:pass@host/...` shape) before encrypting/storing.

## Tests
- `tests/test_simplefin_connect.py` § `"test_connect_with_valid_token_succeeds"` — covers § POST /connect contract (exchange mocked, everything else real).
- `tests/test_simplefin_connect.py` § `"test_connect_without_token_returns_401"` — covers § POST error case: no access token.
- `tests/test_simplefin_connect.py` § `"test_connect_as_demo_user_returns_403"` — covers § POST error case: demo user.
- `tests/test_simplefin_connect.py` § `"test_connect_missing_setup_token_returns_400"` — covers § POST error case: missing field.
- `tests/test_simplefin_connect.py` § `"test_connect_invalid_base64_returns_400"` — covers § POST error case: invalid base64.
- `tests/test_simplefin_connect.py` § `"test_connect_non_https_decoded_url_returns_400"` — covers § POST error case: non-https decoded URL.
- `tests/test_simplefin_connect.py` § `"test_connect_https_but_untrusted_domain_returns_400"` — covers § POST error case: SSRF domain allowlist rejection.
- `tests/test_simplefin_connect.py` § `"test_connect_exchange_redirect_is_not_followed"` — covers § POST error case: redirect not followed.
- `tests/test_simplefin_connect.py` § `"test_connect_oversized_response_returns_502"` — covers § POST error case: oversized response body.
- `tests/test_simplefin_connect.py` § `"test_connect_malformed_response_body_returns_502"` — covers § POST error case: malformed/non-URL response body, confirms nothing gets stored.
- `tests/test_simplefin_connect.py` § `"test_connect_with_bad_claim_url_returns_502"` — covers § POST error case: exchange rejected, sanitized error.
- `tests/test_simplefin_connect.py` § `"test_reconnect_replaces_existing_connection"` — covers § POST contract: reconnecting replaces, doesn't conflict.
- `tests/test_simplefin_connect.py` § `"test_status_returns_false_when_not_connected"` / `"test_status_returns_true_after_connecting"` — covers § GET /status contract.
- `tests/test_simplefin_connect.py` § `"test_status_without_token_returns_401"` — covers § GET error case: no token.

All 11 confirmed red (404, no routes yet) before commit. No external network dependency — verified reliable across 3 consecutive full reruns after the mock-boundary correction (see Notes).

## Changes
- 002 (2026-08-10) — initial contract, within `changes/002-simplefin-and-transactions/plan.md`.
- 002 (2026-08-10) — built. 15 tests green (11 original + 4 added from the security review). Mock-boundary and security findings documented above.
