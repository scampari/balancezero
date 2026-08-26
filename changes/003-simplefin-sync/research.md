# Research: SimpleFIN /accounts sync

> Date: 2026-08-26
> Why: `context/simplefin-integration.md` (written 2026-07-31) explicitly flagged
> re-verification as needed before implementing sync. Confirmed against live docs
> before locking plan constraints.

## Sources
- https://www.simplefin.org/protocol.html — response shape
- https://beta-bridge.simplefin.org/info/developers — rate limit, date range

## Findings vs. the 2026-07-31 note

**Confirmed, unchanged:**
- Auth/claim flow, sign convention (positive = inflow), 90-day max range, "not a
  queue/worker system" framing.
- Rate limit: 24 requests/day per access token.

**New detail, not in the original note:**
- **Account object fields**: `id`, `name`, `conn_id`, `currency`, `balance`,
  `available-balance`, `balance-date` (UNIX epoch), `transactions[]`.
- **Transaction object fields**: `id`, `posted` (UNIX epoch, **0 if pending**),
  `amount`, `description`, `transacted_at` (UNIX epoch, optional), `pending`
  (bool, optional).
- **`posted=0` for pending transactions** is a real tension against
  `Transaction.posted_at` being `NOT NULL` in our schema — see plan's Grill,
  Finding: "Pending transaction posted_at".
- **Partial failure is possible inside a `200`**: a top-level `errlist`/`errors`
  array can carry per-connection or per-account errors (e.g. one linked
  institution broken) alongside otherwise-successful data. A `200` does not
  imply every account synced cleanly.
- **Rate limit enforcement is graduated, not a hard cliff**: exceeding the
  *expected* rate first produces warnings in the errors array; only going
  *significantly* over disables the token. Lowers the stakes of getting the
  client-side counter's exact reset-window semantics perfectly right — see
  plan's Grill, Finding: "Rate-limit tracking."
- **SimpleFIN's own recommendation: overlap the date window by ~5 days** on
  each incremental fetch, specifically to avoid missing transactions that
  post or backdate late. Directly informs the sync's `start-date` calculation.

## Promoted to context/
Folded into `context/simplefin-integration.md` as an agent-proposed addendum
(marked unconfirmed by a human) — see that file's new "Sync details" section.
