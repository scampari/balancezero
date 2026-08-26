# Open Questions: SimpleFIN sync

> Last updated: 2026-08-26

No blocking questions — every low-confidence item had a safe, cheap-to-correct
default available, so nothing here stops `spec/simplefin-sync.md` from moving
to test-planning. All items below are assumptions test-planning should pin
down as real contract decisions, not re-open as design questions.

## Assumptions (agent proceeding unless corrected)

### Not-connected-user sync response code
- **Status:** assumption-accepted
- **Confidence:** medium
- **Slices affected:** `simplefin-sync.md`
- **What I'm assuming:** `POST /api/simplefin/sync` returns `409` when the
  authenticated user has no `simplefin_access_url_encrypted` set (never
  connected, or demo — though demo gets its own `403` first).
- **Rationale:** `400` implies bad input (there is none here — the request
  is fine, the account state isn't); `403` is already used for ownership/
  demo-guard errors elsewhere in this codebase and reusing it here would
  blur two different meanings. `409` (conflict/precondition-failed-ish) is
  the closest fit and isn't used for anything else yet in this API.
- **If wrong, impact:** A one-line status-code change in the contract and
  test; no cascading design impact.
- **Correction:** _(filled by human if wrong)_
- **Resolution:** _(filled once test-planning locks it)_

### Rate-limit cap number and storage shape
- **Status:** assumption-accepted
- **Confidence:** medium
- **Slices affected:** `simplefin-sync.md`
- **What I'm assuming:** A rolling-window (not calendar-day) counter,
  capped conservatively below SimpleFIN's real 24/day limit, stored as new
  column(s) on `User` (not a separate table) — this is a low-volume,
  single-connection-per-user feature, a full audit table is more than it
  needs.
- **Rationale:** Rolling window sidesteps not knowing SimpleFIN's actual
  reset semantics (undocumented); a `User`-column approach matches the
  existing pattern (`simplefin_access_url_encrypted` already lives there)
  rather than introducing a new table for one counter.
- **If wrong, impact:** Migration/model shape changes, but isolated to this
  slice — nothing downstream depends on the storage shape.
- **Correction:** _(filled by human if wrong)_
- **Resolution:** _(filled once test-planning locks it)_

### Response body size cap for the outbound /accounts call
- **Status:** assumption-accepted
- **Confidence:** medium
- **Slices affected:** `simplefin-sync.md`
- **What I'm assuming:** A bounded streamed read (same technique
  `simplefin_api.py::_exchange_for_access_url` already uses for
  `/connect`), sized in the low-single-digit-MB range rather than the 4KB
  used for the connect exchange — an accounts+transactions payload is
  legitimately larger than an access-URL response.
- **Rationale:** Carries forward the connect slice's own security-review
  finding (unbounded response body) proactively, per the plan's Grill.
  Exact byte value needs a realistic sense of Sam's actual transaction
  volume, which test-planning is better positioned to reason about.
- **If wrong, impact:** A constant tweak, not a design change.
- **Correction:** _(filled by human if wrong)_
- **Resolution:** _(filled once test-planning locks it)_

### Sync response shape
- **Status:** assumption-accepted
- **Confidence:** medium
- **Slices affected:** `simplefin-sync.md`
- **What I'm assuming:** `POST /api/simplefin/sync` returns structured
  counts, roughly `{"accounts_synced": N, "transactions_new": X,
  "transactions_updated": Y, "errors": [...]}` — exact keys TBD by
  test-planning.
- **Rationale:** Matches this codebase's existing pattern of returning
  meaningful JSON shape rather than a bare status string (see
  `transactions.md`'s list/patch responses).
- **If wrong, impact:** Response-shape-only change; no other slice consumes
  this response yet (no frontend work is in scope for this change).
- **Correction:** _(filled by human if wrong)_
- **Resolution:** _(filled once test-planning locks it)_

### Pending-transaction posted_at placeholder
- **Status:** assumption-accepted
- **Confidence:** medium
- **Slices affected:** `simplefin-sync.md`
- **What I'm assuming:** When SimpleFIN reports `posted: 0` (pending), use
  `transacted_at` if present, else the sync run's own date, as
  `Transaction.posted_at` — self-corrects on the next sync once the real
  `posted` value arrives.
- **Rationale:** Avoids relaxing `posted_at` to nullable, which every
  existing consumer (the transactions list, its month filter) assumes is
  non-null. Self-correcting keeps the blast radius of a wrong guess small.
- **If wrong, impact:** Pending transactions might show a slightly-off date
  in the UI until they post — cosmetic, not a data-integrity issue (the
  `simplefin_transaction_id` unique key is unaffected).
- **Correction:** _(filled by human if wrong)_
- **Resolution:** _(filled once test-planning locks it)_
