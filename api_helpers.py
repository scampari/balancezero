from datetime import date

from flask_jwt_extended import get_jwt_identity


def current_user_id():
    return int(get_jwt_identity())


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
