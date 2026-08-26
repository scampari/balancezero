# SimpleFIN Bridge integration (superseded)

**Superseded 2026-08-26 by `context/plaid-integration.md`** — SimpleFIN
replaced by Plaid, full replacement decided after grilling the pivot (see
`changes/004-plaid-and-self-host/grill-findings.md`). Kept here for history;
`spec/simplefin-connect.md` (built) and `spec/simplefin-sync.md` (stub) will
be marked superseded once their Plaid equivalents exist. Do not build new
work against this file.

Researched 2026-07-31 (see `~/Desktop/CICD/BALANCEZERO-SCOPE.md` for original notes). Sources: [SimpleFIN Protocol](https://www.simplefin.org/protocol.html), [SimpleFIN Bridge Developer Guide](https://beta-bridge.simplefin.org/info/developers) — re-verify against current docs before implementing, given time elapsed.

- **Auth flow**: user generates a one-time Setup Token from SimpleFIN's UI (`bridge.simplefin.org/simplefin/create`). The app base64-decodes it to a claim URL, POSTs once to exchange it for a permanent **Access URL** with HTTP Basic Auth credentials embedded (`https://<user>:<pass>@bridge.simplefin.org/simplefin`). The app never sees the user's actual bank login credentials.
- **Data access**: `GET /accounts` on the Access URL returns connections, accounts (balance, available-balance, balance-date), and transactions (amount, description, posted date, pending flag). Supports `start-date`/`end-date`, `account`, `pending=1`, `balances-only=1` filters.
- **Rate limit**: 24 requests/day per access token, 90-day max range per request; exceeding it disables the token. Rules out on-demand/real-time sync — needs a scheduled job (cron-style), a few times a day, comfortably under the cap. Not a queue/worker system — unnecessary at this request volume.
- **Sign convention**: amounts are positive = inflow, negative = outflow. `models.py`'s `Transaction.amount` already follows this convention.
- **Security requirement, stated by SimpleFIN itself**: the Access URL must be stored "at least as securely as the user's financial data" — encrypted at rest, not a plaintext DB column. `User.simplefin_access_url_encrypted` (LargeBinary) already anticipates this with Fernet ciphertext. HTTPS only, verify TLS, sanitize error messages before ever displaying them to a user.
- **Demo user**: has no SimpleFIN connection at all — `simplefin_access_url_encrypted` stays null, accounts/transactions are seeded synthetically (`seed_demo.py` already exists). Never call SimpleFIN on behalf of the demo user.

## Sync details (proposed by agent — not yet human-confirmed)

Re-verified 2026-08-26 against current docs (see `changes/003-simplefin-sync/research.md`) — the note above was flagged stale.

- **Account object fields**: `id`, `name`, `conn_id`, `currency`, `balance`, `available-balance`, `balance-date` (UNIX epoch), `transactions[]`.
- **Transaction object fields**: `id`, `posted` (UNIX epoch, **0 if pending**), `amount`, `description`, `transacted_at` (UNIX epoch, optional), `pending` (bool, optional).
- **Partial failure inside a `200`**: a top-level `errlist`/`errors` array can carry per-connection/per-account errors alongside otherwise-successful data — a `200` doesn't mean every account synced cleanly.
- **Rate-limit enforcement is graduated**: exceeding the expected rate first warns (in the errors array), only going significantly over disables the token — not a hard single-request cliff.
- **SimpleFIN's own recommendation**: overlap each incremental fetch's date window by ~5 days (`start-date` = last sync time minus 5 days) to avoid missing late-posting or backdated transactions.
