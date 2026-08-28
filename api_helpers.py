import re
from datetime import date
from difflib import SequenceMatcher

from flask_jwt_extended import get_jwt_identity

from models import Account, Category, Transaction, db

# spec/plaid-sync.md § Manual-transaction adoption. A synced transaction
# adopts a pre-entered manual row only when their descriptions score at
# least this on `description_similarity`. Deliberately strict: it will miss
# a match whenever the typed text differs a lot from the bank's merchant
# string (accepted, in exchange for near-zero false positives).
DESCRIPTION_MATCH_THRESHOLD = 0.80

_NON_ALNUM_RUN = re.compile(r"[^a-z0-9]+")


def _normalize_description(text):
    """Lower-case, then collapse every run of non-alphanumeric characters to
    a single space, trimmed — e.g. "Whole Foods Mkt — 5th Ave!" becomes
    "whole foods mkt 5th ave"."""
    return _NON_ALNUM_RUN.sub(" ", (text or "").lower()).strip()


def description_similarity(a, b):
    """Ratio in [0, 1] of how alike two transaction descriptions are, after
    normalization — `difflib.SequenceMatcher` on the normalized strings, no
    substring shortcut. Used by Plaid sync to decide whether an incoming
    transaction is one the user already entered by hand."""
    return SequenceMatcher(None, _normalize_description(a), _normalize_description(b)).ratio()


def current_user_id():
    return int(get_jwt_identity())


def category_has_children(category_id):
    """True if the category has at least one non-archived subcategory — it's
    a group total, not a spendable/allocatable line (see spec/budget-api.md)."""
    return (
        db.session.query(Category.id)
        .filter(Category.parent_id == category_id, Category.archived.is_(False))
        .first()
        is not None
    )


def is_payment_category(category_id):
    """True if the category is an auto-created credit-card payment envelope
    (changes/021). Transactions can't be assigned to one — its balance is
    driven by card activity, not manual categorization."""
    return (
        db.session.query(Category.id)
        .filter(Category.id == category_id, Category.payment_account_id.isnot(None))
        .first()
        is not None
    )


def infer_category_id(user_id, description, cache=None):
    """Auto-categorize by reuse: the category from the user's most recent
    *categorized* transaction with the exact same description (same
    merchant), or None if there's never been one. Callers apply this only
    to brand-new, uncategorized transactions — it never overrides a choice
    the user already made. `cache` is an optional dict the caller reuses
    across a batch (e.g. one sync) so each distinct description is looked
    up once."""
    if cache is not None and description in cache:
        return cache[description]

    # Exclude a category that has since become a group — a transaction can't
    # be assigned to one (see spec/budget-api.md).
    is_group = (
        db.session.query(Category.id)
        .filter(Category.parent_id == Transaction.category_id, Category.archived.is_(False))
        .exists()
    )
    # ...and never auto-target an auto-created credit-card payment envelope
    # (changes/021). A separate correlated subquery, not a join, so it doesn't
    # collide with the is_group subquery's Category reference.
    is_payment = (
        db.session.query(Category.id)
        .filter(Category.id == Transaction.category_id, Category.payment_account_id.isnot(None))
        .exists()
    )
    prior = (
        db.session.query(Transaction.category_id)
        .join(Account, Transaction.account_id == Account.id)
        .filter(
            Account.user_id == user_id,
            Transaction.description == description,
            Transaction.category_id.isnot(None),
            ~is_group,
            ~is_payment,
        )
        .order_by(Transaction.posted_at.desc(), Transaction.id.desc())
        .first()
    )
    result = prior[0] if prior is not None else None
    if cache is not None:
        cache[description] = result
    return result


def parse_month(raw_month):
    try:
        return date.fromisoformat(raw_month)
    except (TypeError, ValueError):
        return None


def month_bounds(month):
    """[first-of-month, first-of-next-month) — a half-open range for filtering
    Transaction.posted_at to a single calendar month."""
    next_month = (
        date(month.year + 1, 1, 1) if month.month == 12 else date(month.year, month.month + 1, 1)
    )
    return month, next_month
