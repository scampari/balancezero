# Slicing: opt-in "debt payoff" mode for a credit card

> Date: 2026-09-03
> Status: complete (built 2026-09-03)

## What & Why
A linked credit card that the user is *paying down* (not floating this
month's spending) does not fit the envelope/float model from changes/021:
the card's fixed negative `"Starting Balance"` sits in the auto
`"Credit Card Payments"` envelope as a phantom that never shrinks, every
payment stacks the envelope further negative, and `ready_to_assign` never
reflects that real cash left.

This change adds an opt-in per-card `Account.debt_payoff` flag. When set on
a `type == "credit"` account: no auto payment envelope, the card is
excluded from `get_budget`'s credit-card fold, and its debt lives only in
the account balance — out of the budget. Payoff then works like any other
expense: fund a normal category (that moves `ready_to_assign`), file the
payment transaction there, and changes/028 already makes a categorized
transfer count as spend. Repeat payments auto-file via changes/013 after
the first manual categorization. `_is_transfer` and non-flagged cards are
untouched.

## Spec changes
- `spec/accounts-api.md` — modified — new `PATCH /api/accounts/<int:account_id>`
  taking `{"debt_payoff": <bool>}` (404 not-owned, 400 non-credit type, 400
  bad body); GET serializer gains `debt_payoff`. New `Account.debt_payoff`
  column + Alembic migration. First write route on this API.
- `spec/plaid-sync.md` — modified — `_upsert_account` calls
  `_ensure_payment_category` only when `type == "credit" and not
  account.debt_payoff`. `## Changes` entry.
- `spec/budget-api.md` — modified — Credit-card payment categories section:
  a `debt_payoff` card has no payment envelope and is outside the `_by_card`
  fold; its payments are ordinary categorized spend. `## Changes` entry.
- `spec/reports-api.md` — modified — `exclude_transfers` (default true) now
  hides only *uncategorized* transfers (`transfer = false OR category_id IS
  NOT NULL`), matching budget-api's 028 rule. `## Changes` entry.
- `spec/frontend-app.md` — modified — Accounts view: a "paying this off"
  toggle on `type == "credit"` accounts calling the new PATCH. Budget view:
  a converted card renders as a normal top-level category (no card badges,
  not under "Credit Card Payments").

Not modified: `spec/transactions.md` — auto-categorization (013) already
carries repeat payments onto a normal category; no `transfer` semantics
change.

## Context changes
- `context/budget-glossary.md` (new) — disambiguates three colliding terms
  surfaced by the grill: the `debt_payoff` account flag, the starter
  `"Debt Payments"` category group, and the 021 `"Credit Card Payments"`
  group.

## Constraints
- `Account.debt_payoff` — Boolean, NOT NULL, default false. Migration
  mirrors the `transfer`-flag pattern `ca283921af94`: add with
  `server_default sa.false()`, then `alter_column(server_default=None)`;
  `models.py` default is the source of truth after.
- `PATCH /api/accounts/<int:account_id>`, body `{"debt_payoff": <bool>}`.
  404 if the row is not the caller's; 400 if `account.type != "credit"`;
  400 on missing / non-boolean `debt_payoff`. 200 returns the updated
  account in the same shape as a GET list entry. Direct `Account.user_id`
  ownership filter (per accounts-api Notes).
- Setting `debt_payoff` true, when a linked payment `Category` exists
  (`payment_account_id == account.id`): in the same DB transaction as the
  flag write, set its `payment_account_id = NULL` and `parent_id = NULL`
  (top-level), re-pack the top-level sibling `position` sequence per the
  006 reorder rule, keep `name` and every `BudgetAllocation` row. If its
  former parent payments group is then left with zero non-archived
  children, archive that group in the same transaction (so it does not
  become a stray budgetable line — grill). This server-side mutation is
  exempt from the 021 public-route guard that 400s a `parent_id` change on
  a payment category: by commit the row is no longer a payment category,
  and the category route itself is untouched. Setting it false: no
  category work — the next sync's `_ensure_payment_category` creates a
  fresh envelope (`_payment_category_name` suffixes it if the converted
  category still holds the plain name).
- Flip-time discontinuity is expected and asserted: converting a card with
  a −$X `"Starting Balance"` and prior payoff allocations steps that
  category's `available` (and `totals.available`) up by
  `|cc_opening| + moved_in − cc_payments` — the debt leaves the budget.
  After conversion a purchase charged to the card is single-sided (lowers
  its spending envelope, no payment-envelope credit); 021's "the two net
  out" is scoped to non-`debt_payoff` cards.
- Precondition (documented, not enforced): the payment must arrive as a
  categorizable negative transaction on a synced paying account (linked
  autopay — the target case) or be entered manually. A card paid from an
  unlinked account with no manual entry stays invisible to the budget.
- `get_budget` gets no `debt_payoff` branch: a converted / absent payment
  category has no `payment_account_id`, so it is already outside
  `account_by_payment_cat` and the `_by_card` fold. Card purchases stay
  ordinary spend in their own categories; the payment outflow counts once
  filed to a category (changes/028).
- `_is_transfer` and every other Plaid transfer rule unchanged. The
  payment outflow stays `transfer = true`; `infer_category_id` (013) files
  repeat payments after the first manual categorization (it already works
  on normal categories — only payment envelopes are excluded).
- Reports `exclude_transfers` default flips from `transfer = false` to
  `transfer = false OR category_id IS NOT NULL`. `exclude_transfers=false`
  still returns every row.
- Money stays `Decimal`, 2dp. Tests: pytest, real Postgres via Docker,
  Flask test client.

## Non-Goals
- No change to `_is_transfer` / Plaid transfer classification.
- No change to envelope/float budgeting for cards not flagged `debt_payoff`.
- No `debt_payoff` on `type == "loan"` or any non-credit account — the
  PATCH rejects them.
- Not touching the `ready_to_assign` formula — it moves only through
  normal funding of the payoff category.
- No automatic categorization of the first payment; no historical backfill
  of past payments (self-heal going forward, like 028).
- No connect-flow change — the toggle lives only in the Accounts view.
- No dedicated debt-payoff planning / target UI — an ordinary category
  target (005/006) already covers it.
- No solution for cards paid from unlinked accounts beyond the existing
  manual-transaction flow (grill precondition).
- The converted category is not auto-filed under the starter "Debt
  Payments" group — it lands top-level; the user moves it if they want.

## Build skills
- `frontend-build` — Accounts toggle + Budget page rendering in the React
  SPA. Backend is plain Flask/SQLAlchemy, no special skill.

## First slice
- `spec/accounts-api.md` — the `debt_payoff` column, the PATCH endpoint,
  and the in-place conversion of an existing payment category. Foundation
  for the budget / reports / frontend slices; depends only on the model
  change.

## Open Questions
- Position re-pack on reparent: reuse the `PATCH /api/categories` reorder
  helper from the accounts handler, or just append the converted category
  at the end of the top-level group and leave finer ordering to a manual
  reorder? (build detail)
- Should a converted category carry any subtle "was a card payment" hint in
  the budget UI, or be indistinguishable from a hand-made category?
  (leaning indistinguishable — frontend slice)
- Reports `by_category` grouping: does it need an explicit "uncategorized
  transfers excluded" affordance, or is silent exclusion fine? (reports
  slice / test-planning)

## Test planning result

Contracts landed 2026-09-03. All 5 in-scope specs edited in place; no new
spec files (the `spec/README.md` index is unchanged — statuses stay
`built` with a "Not yet built" 029 `## Changes` entry each, per the 023
precedent).

### Spec files modified
- `spec/accounts-api.md` — new `### PATCH /api/accounts/<int:account_id>`
  contract (setup / action / input / output / side effects), 5 error
  cases, GET serializer `debt_payoff` field, a frontend toggle e2e
  contract, `Account.debt_payoff` migration note, `## Tests` placeholders,
  `## Changes` 029.
- `spec/budget-api.md` — new "Debt-payoff cards (029)" bullet in the
  contract body (envelope exclusion, flip-time `available` /
  `totals.available` step-up, single-sided card purchase, categorized
  payment counts via 028, `ready_to_assign` unchanged); reworded the 021
  "the two net out" clause to scope it to non-flagged cards; `## Changes`
  029 enumerating 6 backend test cases + the frontend note.
- `spec/plaid-sync.md` — `## Changes` 029: `_ensure_payment_category`
  skipped when `type == "credit" and account.debt_payoff`, with a
  two-credit-account sync contract.
- `spec/reports-api.md` — `## Done when` `exclude_transfers` line rewritten
  ("hide only uncategorized transfers"); new `#### exclude_transfers cases
  (changes/029)` with 3 cases + the "no new disclosure field" note;
  `## Changes` 029.
- `spec/frontend-app.md` — unchanged (frozen at the walking skeleton;
  frontend rides in `accounts-api.md` / `budget-api.md` 029 entries, per
  the 025 precedent).

### Resolved open questions
- Position on reparent → **append last top-level, re-pack gap-free** (006
  rule). Test asserts last-by-position.
- Reports hidden-bucket disclosure → **silent**, no new field.
- "Was a card" hint on the converted category → **none** — indistinguishable
  from a hand-made category (no test impact).

### Mock boundaries
- All real: Postgres (Docker) + Flask test client, same as every
  `budget_api` / `accounts_api` / `reports_api` test.
- Plaid-sync 029 test runs **offline** against a seeded `PlaidItem` with a
  mocked `transactions_sync` — the established `plaid-sync.md` pattern for
  non-`@requires_plaid_sandbox` cases.
- Frontend: real browser (Playwright) + real backend + Vite dev server.
- No new mock boundary; nothing to add to `context/testing.md`.

### Context updates
- `context/budget-glossary.md` created in the grill step (three colliding
  debt terms). No further context change from test-planning.

### Test infrastructure notes
- New `frontend/e2e/accounts.spec.ts` + a seed for a user with one credit
  and one depository account (extend `seed_e2e_*`).
- `seed_e2e_budget.py` gains a converted-card (debt-payoff) category row
  for the budget-render assertion.
- `credit_account` conftest fixture is reused for the conversion /
  emptied-group tests; a two-card variant is needed for the
  "group stays active" case (inline in the test, no new fixture required).

## Test writing result

Red tests committed 2026-09-03 (test-writer). 19 new tests, all failing for
the right reason; 167 pre-existing tests across the four touched files still
pass; 2 `@requires_plaid_sandbox` skipped.

- `tests/test_accounts_api.py` +13 — PATCH contract, conversion side
  effects, emptied-group archive, shared-group stays active, no-payment-cat
  case, idempotency, `x → false`, and the `401` / `404` / `400` error
  cases. Red: PATCH route → `404`.
- `tests/test_budget_api.py` +6 — no payment envelope after conversion;
  the `−$800 → $200` / `totals.available +$1000` flip; single-sided card
  purchase; categorized payment outflow counts (028 path); emptied-group
  archive in the budget view; `ready_to_assign` unchanged. Red: PATCH is a
  no-op so the fixture stays a payment envelope.
- `tests/test_plaid_sync.py` +1 — `_ensure_payment_category` skip across
  two syncs, non-flagged card unaffected. Red: `TypeError` — no
  `debt_payoff` column.
- `tests/test_reports_api.py` +1 — a categorized transfer counts by
  default. Red: `expense` is `40.00`, not `140.00`.
- `frontend/e2e/accounts.spec.ts` (new) + `seed_e2e_accounts.py` (new) —
  the credit-only "paying this off" toggle calls the PATCH and persists.
- `## Tests` forward-pointers written into all four specs.

Build order: `spec/accounts-api.md` first (column + migration + PATCH +
conversion), then the `_ensure_payment_category` guard, then reports, then
the frontend toggle. `budget_api.py` needs no logic change — its 6 tests
should pass once conversion lands.

## Build result

Built 2026-09-03 (inline). All slices green; `budget_api.py` needed no
logic change, exactly as planned.

- Slice 1 — `models.py` `Account.debt_payoff` + migration `3f1c9a2b7d84`;
  `accounts_api.py` `_serialize_account` + `PATCH /api/accounts/<id>`;
  `budget_api.convert_payment_category_to_plain` (mirrors the
  `patch_category` reparent path, then archives an emptied group).
- Slice 2 — `plaid_api._upsert_account`: `_ensure_payment_category` gated
  on `not account.debt_payoff`.
- Slice 3 — `reports_api.py`: `exclude_transfers` →
  `or_(transfer.is_(False), category_id.isnot(None))`.
- Slice 4 — `client.ts` `Account.debt_payoff` + `setAccountDebtPayoff`;
  `AccountsPage.tsx` credit-only `role="switch"` "Paying this off" toggle.
  Reworded the helper copy ("automatic payment envelope", not "Credit Card
  Payments") after it collided with `plaid-institutions.spec.ts`'s
  `getByText('Credit Card')`.

Backend: 296 passed / 7 skipped. Frontend: `tsc -b` clean, `oxlint` clean
(2 pre-existing warnings). E2E: `accounts.spec.ts` green + full suite green
(one pre-existing intermittent flake seen once, not reproduced).

Migration note: neither `pytest` (conftest `create_all`) nor the e2e suite
(`seed_e2e.py` `create_all`) exercises `3f1c9a2b7d84` — it needs
`flask db upgrade` against the real DB on deploy.

## Grill

### Tension: conversion drops the `cc_opening` / `moved_in` fold — `totals.available` jumps at flip time and 021's "the two net out" stops holding for the card
**Challenge:** a payment envelope's `available` is `Σalloc + moved_in −
cc_payments + cc_opening` (`budget_api.py:516-523`). Conversion makes it the
plain `allocated_through + spent_through_end`. The card's negative
`"Starting Balance"` (`cc_opening`, e.g. −$1,000) and any `moved_in` from
card purchases leave budget math in the same instant, so (a) that
category's `available` and `totals.available` step up by
`|cc_opening| + moved_in − cc_payments` on flip, and (b) a *future*
purchase charged to the card lowers its spending envelope with no
offsetting payment-envelope credit — 021's "one envelope down, the payment
envelope up, net zero in `totals.available`" no longer holds for this card.
**Resolution:** intended. (a) *is* "pull the debt out of the budget"; (b)
is correct for a card you are not floating. Made explicit: plan constraint
below, test-planning asserts the flip-time jump and asserts a later card
purchase is single-sided, and `spec/budget-api.md`'s 021 section is
reworded to scope "the two net out" to non-`debt_payoff` cards.
**Write-back:** plan constraint + non-goal; `spec/budget-api.md` 021-section
wording (test-planning).

### Tension: the mechanism needs a categorizable payment *outflow* row — absent for a card paid from an unlinked / manual account
**Challenge:** "payments become ordinary categorized spend" relies on the
paying account's `LOAN_PAYMENTS_CREDIT_CARD_PAYMENT` outflow being synced so
the user can file it to the payoff category. If the paying account is not
linked, the only artifact is the card-side *inflow* (`amount > 0`), and
filing a positive amount to a spend category *reduces* spend. For those
users, flipping the flag yields "payment invisible to the budget" — the
opposite of the stated need.
**Resolution:** documented as a precondition, not solved here. The user's
case is linked-checking autopay (they connected a card and pay via a
Plaid-visible transfer), where it is a one-time categorization then
automatic (013). Manual-payment users use the existing manual-transaction
flow: enter the payment as a negative transaction on the paying account and
categorize it, same as any manual expense. Toggle copy in
`spec/frontend-app.md` must not promise automatic tracking.
**Write-back:** plan precondition + non-goal.

### Terminology: "debt payoff" flag vs. starter "Debt Payments" group vs. 021 "Credit Card Payments" group
**Collision:** `starter_categories.py` already ships a top-level
`"Debt Payments"` group (child `"Loans"`); 021 owns `"Credit Card
Payments"`. The new flag is `debt_payoff` and the plan reparents the
converted category to **top-level** — orphaned next to, but not inside, the
user's existing "Debt Payments" bucket. Three debt-flavoured names, and the
one natural home for the converted category is the place the plan doesn't
put it.
**Resolution:** keep the column name `debt_payoff` — it names an *account*
property, not a category, so there is no data-model collision. Do not
hard-code reparenting into "Debt Payments" (user-editable, may be renamed /
archived / absent). Reparent to top-level as planned; the frontend slice
makes it a one-drag move under any group. Disambiguation written to
`context/budget-glossary.md`.
**Write-back:** `context/budget-glossary.md` (new); plan constraint
clarified.

### Tension: an emptied "Credit Card Payments" group silently becomes a normal budgetable line
**Challenge:** `is_group` is derived (`parent_id is None` and ≥1
non-archived child, `budget_api.py:408,544`). Convert the only card and
`"Credit Card Payments"` has zero children → it stops being a group and
becomes a plain allocatable / spendable top-level category the user never
created.
**Resolution:** on conversion, if the parent payments group is left with no
non-archived children, archive that empty group in the same transaction.
Added to plan constraints; test-planning covers the single-card case.
**Write-back:** plan constraint.

### Prior-decision conflict: 021 guard "PATCH changing `parent_id` on a payment category → 400"
**Challenge:** 021 hard-blocks `parent_id` changes on a payment category;
the conversion mutates `parent_id` and `payment_account_id` on exactly such
a row.
**Resolution:** not a violation. The guard is on the public
`PATCH /api/categories/<id>` route driven by user input. The conversion is
a server-side effect of `PATCH /api/accounts/<id>`, in the same
transaction that clears `payment_account_id` (so by commit the row is no
longer a payment category). The category-route guard is unchanged; the plan
states this so it is not "quietly re-decided."
**Write-back:** plan constraint note.

### Refutation: the simpler version is "archive, don't convert" — no column, no endpoint, no migration
**Argument:** relax the 021 archive guard to allow archiving a payment
category, drop archived payment categories from the `_by_card` fold, and
stop `_ensure_payment_category` resurrecting it. "Archived payment
category" *is* the debt-payoff signal — no `Account.debt_payoff`, no
`PATCH /api/accounts`, no migration, 2 specs instead of 5.
**Resolution:** does not hold. (1) The user explicitly chose "convert in
place, keep the allocations already budgeted to payoff" over "archive +
start fresh" — archiving strands those allocations in a hidden row and
forces re-budgeting. (2) "Archived payment category" is an implicit state
discoverable only by reading code; an account-level flag is the honest
model for "this account is a debt I'm paying down," is visible in the
accounts API, and is where future behavior (reports, net-worth, targets)
will look. The extra column + endpoint + migration is small and follows
the exact `transfer`-flag precedent (`ca283921af94`). The refutation's
"don't over-build" spirit is kept: no `loan` support, no connect-flow
change, no new target UI.

### Confirmed (grill asks b, d)
- **A categorized transfer reliably counts as spend for a converted
  top-level category — yes.** `spent_this_month` / `spent_through_end`
  filter only `category_id == cat.id` + `posted_at` bounds; the
  `transfer.is_(False)` filter was removed in 028 (`budget_api.py:431-440`).
  The only special-casing was `is_payment_category` rows forced to
  `spent_this_month = 0` (`budget_api.py:524`) — conversion removes exactly
  that status. Auto-categorization fires for a `transfer=True` new row
  (`_upsert_transaction` gates only on `is_new`, no `category_id`, not
  `is_income`).
- **Manual-first + 013 is acceptable, not a gap, for the target user.**
  One categorization then automatic on every repeat payment — the same as
  every other recurring expense in the app. The genuine gap
  (manual-payment accounts) is the second tension above.
