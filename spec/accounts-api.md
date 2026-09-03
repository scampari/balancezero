---
status: built
depends_on: [auth.md, plaid-connect.md]
---

# Accounts API: list connected bank accounts

## Does
Lets a user see their bank accounts (name, balance, available balance,
last-updated date) — the first UI surface for what `plaid-connect.md` and
`plaid-sync.md` actually populate. No new data model — `Account` already
exists and is already written by sync; this slice is the first thing that
reads it back out for the user.

Also (changes/029) lets a user flag a credit card as **debt payoff** —
`PATCH /api/accounts/<id>` with `{"debt_payoff": true}`. A flagged card
drops its auto `"Credit Card Payments"` envelope and its debt leaves the
budget; payments become ordinary categorized spend (see
`spec/budget-api.md` changes/029).

## Done when
- A user can list their own accounts, seeing current balance and available
  balance for each.
- The demo user sees their synthetic seeded accounts (no Plaid connection
  required — accounts exist independent of `plaid_account_id`).
- Per-user data isolation holds — an account is only visible to its
  owning `user_id`.
- No Plaid identifiers (`plaid_account_id`) are exposed in the response —
  internal, not needed by any current UI.
- A user can set / clear `debt_payoff` on a `type == "credit"` account and
  see it reflected in the list. Setting it on a card that still has a bound
  payment category converts that category to a plain top-level category in
  the same request (keeps its name and every allocation).

## Integration test contract

### GET /api/accounts

**Setup:** An authenticated user with at least one account.
**Action:** `GET /api/accounts`, `Authorization: Bearer <access token>`.
**Input:** None.
**Expected output:** `200`, JSON `{"accounts": [{"id": ..., "name": ...,
"type": "..." | null, "subtype": "..." | null, "currency": ...,
"balance": "...", "available_balance": "..." | null,
"balance_date": "..." | null, "debt_payoff": false}]}`. Only the
authenticated user's own accounts. `plaid_account_id` never appears in the
response. `type` / `subtype` are Plaid's classification (changes/018),
null for demo/manual/pre-018 rows. `debt_payoff` (changes/029) is a
boolean, `false` for every row until a user sets it.

#### Error cases
- **When no/invalid access token, Then** `401`.

### PATCH /api/accounts/<int:account_id> (changes/029)

**Setup:** An authenticated user owning a `type == "credit"` `Account`.
Optionally that card already has its auto `"Credit Card Payments"` group
and a bound payment `Category` (the state `_ensure_payment_category`
produces — the `credit_account` fixture), and that payment category may
already carry `BudgetAllocation` rows.
**Action:** `PATCH /api/accounts/<account_id>`,
`Authorization: Bearer <access token>`, JSON body.
**Input:** `{"debt_payoff": <bool>}` — the only writable field; any other
key in the body is ignored.
**Expected output:** `200`, JSON
`{"account": {<same shape as one GET /api/accounts list entry>}}` with
`debt_payoff` equal to the new value.
**Side effects:**
- `Account.debt_payoff` is set to the given value.
- **On a `false → true` transition when a bound payment `Category` exists**
  (`payment_account_id == account.id`), in the same DB transaction as the
  flag write:
  - its `payment_account_id` is set to `NULL`;
  - its `parent_id` is set to `NULL` (top-level);
  - it is placed **last** among the user's top-level categories and the
    whole top-level `position` sequence is re-packed gap-free `0..n-1`
    (the changes/006 reorder rule);
  - its `name` and every `BudgetAllocation` row are left untouched.
- **If that conversion leaves the former parent `"Credit Card Payments"`
  group with zero non-archived children**, that group row is archived
  (`archived = true`) in the same transaction.
- **Any other transition** (`true → true`, `x → false`, or `false → true`
  with no bound payment category): only the flag is written; no `Category`
  or `BudgetAllocation` row changes.
- Never touches `Account.balance`, any `Transaction`, or the card's
  synthetic `"Starting Balance"` row.

This conversion is a server-side effect of the accounts route and is
**exempt** from the changes/021 guard on `PATCH /api/categories/<id>` that
`400`s a `parent_id` / `archived` change on a payment category — by commit
the row is no longer a payment category, and the category route itself is
unchanged.

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `<account_id>` is not an `Account` owned by the caller** (missing,
  or another user's)**, Then** `404` — no existence leak, flag unchanged.
- **When the target `Account.type` is not `"credit"`** (`"depository"`,
  `"loan"`, `"investment"`, or `NULL`)**, Then** `400`, flag unchanged, no
  category changes.
- **When the body omits `debt_payoff`, or `debt_payoff` is not a JSON
  boolean** (`"true"`, `1`, `null`, absent)**, Then** `400`, flag
  unchanged.
- **When `debt_payoff` is set `true` on a card that is already `true`,
  Then** `200`, idempotent — no second conversion, the already-converted
  category and the archived group are left as they are.

### Frontend — "paying this off" toggle on the Accounts view (changes/029)

Playwright e2e against the real backend + Vite dev server (per
`context/testing.md` / `spec/frontend-app.md`).
**Setup:** A seeded user with one `type == "credit"` account (plus its
payment category) and one `type == "depository"` account.
**Action:** Visit `/accounts`; toggle "Paying this off" on the credit-card
row.
**Expected:** the control renders only on the credit-card row, never on the
depository row. Toggling it issues `PATCH /api/accounts/<id>` with
`{"debt_payoff": true}`; on success the control shows the on-state and the
state survives a page reload (read back from `GET /api/accounts`).
**Side effects:** the PATCH side effects above.

## Notes
- **`Account.debt_payoff` (changes/029)** — Boolean, `NOT NULL`, default
  `false`. New Alembic migration on the current head, same shape as the
  `transfer`-flag migration `ca283921af94`: add the column with
  `server_default sa.false()` so the `NOT NULL` add succeeds against
  existing rows, then `alter_column(server_default=None)` — `models.py`'s
  default is the source of truth afterwards.
- **`accounts_api.py` gains its first write route.** Ownership is the
  direct `Account.user_id == current_user_id()` filter already used by the
  `GET` (per the pattern note below) — a non-owned id resolves to `404`,
  not `403`.
- **Toggle copy** must describe the budgeting effect without promising
  automatic payment tracking — e.g. "Its payments count as spending in a
  category you pick," not "payments are tracked for you." The mechanism
  needs the user (or auto-categorization, changes/013) to file each
  payment transaction.
- Reuses the direct `user_id` ownership-filter pattern already established
  in `budget_api.py`/`transactions_api.py` — no join-based ownership check
  needed since `Account.user_id` is direct (unlike `Transaction`, which
  goes through `Account`).
- `balance_date` is `None` for demo/synthetic accounts that have never
  been through a real sync — same nullability already on the column.

## Tests
- `tests/test_accounts_api.py` § `"test_list_accounts_returns_own_accounts"`
  — covers § GET /api/accounts contract.
- `tests/test_accounts_api.py` § `"test_list_accounts_only_shows_own_accounts"`
  — covers § per-user isolation.
- `tests/test_accounts_api.py` § `"test_list_accounts_without_token_returns_401"`
  — covers § error case: no token.
- `tests/test_accounts_api.py` § `"test_list_accounts_excludes_plaid_account_id"`
  — covers § Done-when: no Plaid identifiers leaked.
- `tests/test_accounts_api.py` § `"test_list_accounts_includes_debt_payoff_false_by_default"`
  — covers § GET serializer `debt_payoff` field (changes/029).
- `tests/test_accounts_api.py` § `"test_patch_account_sets_debt_payoff_and_echoes_the_account"`
  — covers § PATCH contract: sets the flag, echoes the account.
- `tests/test_accounts_api.py` § `"test_patch_account_can_clear_debt_payoff"`
  — covers § PATCH `x → false` transition.
- `tests/test_accounts_api.py` § `"test_patch_account_debt_payoff_converts_a_bound_payment_category"`
  — covers § side effect: `false → true` conversion (clears
  `payment_account_id` + `parent_id`, last top-level, positions re-packed,
  name + allocation kept).
- `tests/test_accounts_api.py` § `"test_patch_account_debt_payoff_archives_an_emptied_payments_group"`
  — covers § side effect: emptied `"Credit Card Payments"` group archived.
- `tests/test_accounts_api.py` § `"test_patch_account_debt_payoff_keeps_a_shared_payments_group_active"`
  — covers § side effect: a group with another card's payment category stays active.
- `tests/test_accounts_api.py` § `"test_patch_account_debt_payoff_with_no_payment_category_only_sets_the_flag"`
  — covers § side effect: no-payment-category case writes only the flag.
- `tests/test_accounts_api.py` § `"test_patch_account_debt_payoff_true_is_idempotent"`
  — covers § error case: second `true` is a no-op.
- `tests/test_accounts_api.py` § `"test_patch_account_without_token_returns_401"`
  — covers § error case: no token.
- `tests/test_accounts_api.py` § `"test_patch_account_not_owned_returns_404"`
  — covers § error case: `404` for a foreign row and an unknown id.
- `tests/test_accounts_api.py` § `"test_patch_account_non_credit_type_returns_400"`
  — covers § error case: non-credit `Account.type`.
- `tests/test_accounts_api.py` § `"test_patch_account_non_boolean_debt_payoff_returns_400"`
  — covers § error case: missing / non-boolean `debt_payoff`.
- `frontend/e2e/accounts.spec.ts` § `"the \"paying this off\" toggle is credit-only, calls the API, and persists"`
  + `seed_e2e_accounts.py` — covers § Frontend toggle contract.
- All backend cases confirmed red 2026-09-03 (PATCH route → `404`; the
  `debt_payoff` column → `TypeError` on the sync test); 167 pre-existing
  tests across the four touched files still pass.

## Changes
- 029 (2026-09-03) — contract landed by test-planning. New
  `Account.debt_payoff` (Boolean, NOT NULL, default false) + migration in
  the `ca283921af94` mould. New `PATCH /api/accounts/<int:account_id>`
  (first write route on this blueprint) taking `{"debt_payoff": <bool>}`:
  `404` non-owned, `400` non-credit type, `400` bad body, `200` echoes the
  updated account. On `false → true` with a bound payment `Category`, the
  same request converts it — clears `payment_account_id` + `parent_id`,
  appends it last top-level with a position re-pack, keeps name +
  allocations — and archives the `"Credit Card Payments"` group if that
  empties it. GET serializer gains `debt_payoff`. Frontend: `client.ts`
  account type + a PATCH call, and a credit-only "Paying this off" toggle
  on `/accounts` (`AccountsPage.tsx`); budget-side effects in
  `spec/budget-api.md` 029, sync-side in `spec/plaid-sync.md` 029, reports
  in `spec/reports-api.md` 029. `changes/029-credit-card-debt-payoff`.
  Built 2026-09-03 — migration `3f1c9a2b7d84`; `PATCH` route +
  `_serialize_account` in `accounts_api.py`;
  `budget_api.convert_payment_category_to_plain`. All 13 accounts cases +
  the 6 budget cases green; `get_budget` unchanged.
- 018 (2026-08-27) — serializer gains `type` / `subtype` from the new
  `Account` columns. `tests/test_accounts_api.py` §
  `"test_list_accounts_includes_type_and_subtype"`.
- 005 (2026-08-26) — contract + build in one pass (small, additive,
  interactive session — not routed through the async plan-grill pipeline).
  All 4 tests confirmed red then green.
