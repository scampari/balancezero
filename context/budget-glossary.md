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

## Related

- **`Transaction.transfer`** (changes/019, narrowed 028) — money moved
  between the user's own accounts; excluded from budget math *unless the
  row is categorized* (028). A credit-card payment is still flagged
  `transfer`; `debt_payoff` does not change that — the payment counts once
  the user files it to a category.
