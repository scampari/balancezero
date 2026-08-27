from datetime import date

from flask_jwt_extended import get_jwt_identity

from models import Account, Transaction, db


def current_user_id():
    return int(get_jwt_identity())


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

    prior = (
        db.session.query(Transaction.category_id)
        .join(Account, Transaction.account_id == Account.id)
        .filter(
            Account.user_id == user_id,
            Transaction.description == description,
            Transaction.category_id.isnot(None),
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
