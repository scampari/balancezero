# 030 — Overspend notification + cover-by-moving-money

## Why

Zero-based budgeting only works if overspending gets resolved.
Today the budget page shows a red `available` number and nothing else.
The user has to notice it, work out which envelope has spare cash, and hand-edit two allocation inputs.
The fix should be one click from the alert.

## What changes

A notification on the budget page listing this month's overspent categories, each with a **Cover** action that opens a dialog to move money from another envelope (or from Ready to Assign) into the overspent one.

## Constraints discovered

- **Allocations may not be negative** (`spec/budget-api.md`, decided 2026-08-10).
  Moving money out of an envelope whose balance is carried-in rollover requires exactly that.
  The common case — Groceries has $50 available, all rollover, `allocated_this_month = 0` — is impossible through the existing endpoint.
  Resolved by a separate endpoint (below), leaving the allocations rule untouched.

- **A move is zero-sum across allocations**, so `ready_to_assign` (global: all-time income − all-time allocations) is unchanged by construction.
  No reconciliation math to add.

- **Groups are not allocatable** (`400` on allocation and on transaction assignment).
  A group's `available` is the sum of its children, so a group can read as overspent while no single child is.
  Alerting on a group would be unactionable.

- **Payment envelopes have folded `available`** (changes/021): `moved_in`, `cc_payments`, and `cc_opening` are folded in on top of the raw allocation + spend sum.
  Any move guard that reads `available` must use the same fold, or it will mis-measure a payment envelope.

- **`available` is month-bounded** (changes/025). Overspent is a per-month question, always asked about the viewed month.

## Decisions

### D1 — New endpoint `POST /api/allocations/move`, source allocation may go negative

`{from_category_id: <int> | null, to_category_id: <int>, month: "YYYY-MM-01", amount: "12.34"}`.
Applies a **delta** to both allocation rows in one DB transaction.
The source row may go negative; the existing `POST /api/categories/<id>/allocations` keeps its zero-or-positive rule unchanged.

Rationale: an assignment and a move are different actions.
"Allocations are zero-or-positive" was decided about assignment — the reasoning given was that a negative *assignment* isn't meaningful in zero-based budgeting.
A negative allocation row reached by a move is meaningful: it records that this envelope gave money away.
Rejected the alternative of capping moves at `allocated_this_month`, since that forbids the most common case.
Rejected a separate `EnvelopeMove` table — it adds a third term to every `available` computation for an audit trail nobody asked for.

### D2 — `from_category_id: null` means Ready to Assign

Covering from unassigned money is the most natural fix when the pool is positive, and it is the YNAB-shaped flow the user will expect.
Modelling it as a `null` source keeps one code path in the dialog instead of branching between the move endpoint and the allocations endpoint.
Guard becomes `ready_to_assign >= amount` instead of the source envelope's `available`.

### D3 — Guard: `amount <= source available`

A move can never create a new overspent category.
This is the slice's load-bearing invariant and the reason the endpoint is safe despite permitting negative rows.

### D4 — The notification lists leaf categories only

Groups and archived categories never appear.
Group rows keep their existing red `available` display; they just carry no Cover button, because there is nothing to move money into.

### D5 — Extract a shared `available` helper

`get_budget` and the move endpoint must agree on what an envelope holds, payment-envelope fold included.
Today that math lives inline in `get_budget`.
Extract it so both call one implementation rather than the guard re-deriving it and drifting.

### D6 — Terminology

The user-facing action is **cover**; the mechanism is an **envelope move**.
Deliberately not "transfer" — `Transaction.transfer` already means money between the user's own bank accounts.
Deliberately not "moved in" — `moved_in` already means card spending folding into a payment envelope.
Goes in `context/budget-glossary.md`.

## Specs

| Spec | Change |
|---|---|
| `spec/budget-api.md` | modified — adds the `POST /api/allocations/move` contract; notes the negative-allocation carve-out and the shared `available` helper |
| `spec/frontend-app.md` | modified — adds the overspend banner + Cover dialog contract |

First slice for build: `spec/budget-api.md`.

## Non-goals

- Move history / audit trail. No `EnvelopeMove` table (D1).
- Notifications outside the budget page — no nav badge, no email, no push.
- Auto-covering. The app never picks the source envelope for the user.
- Changing how overspending rolls forward. It still stays inside the category and never touches `ready_to_assign` (changes/025).

## Grill

**Can a move create a new overspend?**
No — D3's guard is exactly this. Worth stating as an invariant in the spec, not just an error case, so a future change can't quietly relax it.

**A group reads overspent but no child is. What does the banner say?**
Nothing. D4. Caught before writing the contract; the naive "list every category with `available < 0`" would have produced an alert with a dead button.

**Does permitting negative allocations break `ready_to_assign`?**
No. `ready_to_assign` sums allocations globally; a move adds `−X` and `+X`. Unchanged by construction. This is the reason D1 is cheap.

**Does it break `totals`?**
`totals.allocated_this_month` sums per-category allocations, so a within-month move leaves it unchanged.
`totals.available` likewise. Correct — the user moved money, they did not gain or lose any.

**Payment envelope as a move source?**
Allowed, but only because D5 makes the guard read the same folded `available` the UI shows.
Without D5 the guard would read the raw allocation sum and let the user overdraw a payment envelope.
This is the one place the slice could have shipped a real bug.

**Term collision.**
"Transfer" was the obvious word and is already taken by `Transaction.transfer`, with a second near-miss in `moved_in`. D6.

**Move in a past or future month?**
Allowed. Allocations already accept any month, and the budget is month-bounded, so restricting moves would be a new asymmetry with no stated reason.

## Verification

- Backend: pytest against real Postgres — the move endpoint's happy path, the `available` guard, the negative-source-row case, and every ownership/validation error. Plus the existing budget suite unchanged, proving `ready_to_assign` and `totals` really are untouched.
- Frontend: Playwright e2e against the real Flask backend and real Vite dev server — seed an overspent category, assert the banner appears, click Cover, complete the move, assert the banner clears and both rows show the new numbers.
- Manual: drive the running app and check the banner and dialog against the existing budget page's visual language.
