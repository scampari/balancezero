# Budget glossary

Load-bearing terms that collide if used loosely. Keep these distinct in
specs, code, and UI copy.

## Debt / credit-card terms

- **`Account.debt_payoff`** (changes/029) — a boolean flag on an `Account`,
  settable only on `type == "credit"`. Means "this card is a balance I am
  paying down, not spending I float." When true: no auto payment envelope,
  the card is excluded from `get_budget`'s credit-card fold, and the debt
  lives only in the account balance. Names an *account* property — never a
  category.

- **"Credit Card Payments" group** (changes/021) — an app-created top-level
  category group holding one *payment envelope* per linked credit card
  (`Category.payment_account_id` set). The envelope's `available` is cash
  set aside to pay that card down; its math folds `moved_in`,
  `cc_payments`, and the card's `cc_opening`. A card flagged `debt_payoff`
  has **no** entry here — its former envelope is converted to a plain
  top-level category.

- **"Debt Payments" group** (`starter_categories.py`, changes/017) — a
  plain starter category group (default child: "Loans"). User-owned and
  fully editable: can be renamed, archived, or deleted. The app never
  writes to it automatically and never files a converted card payment
  under it.

## Moving money between envelopes

- **"Cover"** (changes/030) — the *user-facing* verb for fixing an
  overspent envelope by pulling money into it from somewhere else. What the
  button says. Always about a single overspent category.

- **Envelope move** (changes/030) — the *mechanism* behind Cover: `POST
  /api/allocations/move` applies `−amount` to one category's
  `BudgetAllocation` for a month and `+amount` to another's, in one DB
  transaction. Zero-sum, so `ready_to_assign` and `totals` are unchanged.
  The source row is allowed to go **negative** — the one carve-out from the
  zero-or-positive rule that `POST /api/categories/<id>/allocations` still
  enforces, since an envelope's carried-in rollover is exactly the balance a
  user reaches for and it lives outside `allocated_this_month`. A
  `from_category_id` of `null` means the money comes from
  `ready_to_assign`.

- **Overspent** (changes/030) — an entry in `GET /api/budget`'s
  `categories` with `available < 0` and `is_group` false. Groups are
  excluded because they aren't allocatable, so there is nothing to move
  money into. Not a stored field; derived from the budget view.

Deliberately **not** called a transfer or a "move in" — both words are
already taken, see below.

## Related

- **`Transaction.transfer`** (changes/019, narrowed 028) — money moved
  between the user's own accounts; excluded from budget math *unless the
  row is categorized* (028). A credit-card payment is still flagged
  `transfer`; `debt_payoff` does not change that — the payment counts once
  the user files it to a category.
