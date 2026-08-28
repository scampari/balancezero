"""Spending-habits reporting — one read-only endpoint that returns every
dataset the /reports page renders. Aggregation only; no migration.

Sign/definitions, consistent with budget_api:
  expense  = SUM(-amount) WHERE amount < 0   (reported as a positive number)
  income   = SUM(amount)  WHERE is_income
  net      = SUM(amount)  over every transaction in the bucket (signed:
             + inflow, - outflow) — so a non-income refund nets in here only.
Grouping uses date_trunc / to_char — Postgres, which is prod and the test DB.

Customization (changes/020): filter by account, filter by category/group,
choose the period grain (week / month / quarter / year), and include or
exclude transfers (excluded by default — a card payment isn't spending).
"""

from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import case, func

from api_helpers import current_user_id
from models import Account, Category, Transaction, db

reports_bp = Blueprint("reports_api", __name__, url_prefix="/api")

_DEFAULT_RANGE_MONTHS = 6
_TOP_MERCHANTS = 10
_ZERO = Decimal("0")
_CENTS = Decimal("0.01")

_DEFAULT_GRAIN = "month"
# Per-grain cap on the number of buckets a single response may span — a
# query-cost bound, same spirit as the old flat 24-month cap.
_MAX_BUCKETS = {"week": 53, "month": 24, "quarter": 12, "year": 10}
_GRAINS = tuple(_MAX_BUCKETS)


def _first_of_month(value):
    return value.replace(day=1)


def _add_month(value):
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def _sub_month(value):
    return date(value.year - 1, 12, 1) if value.month == 1 else date(value.year, value.month - 1, 1)


def _parse_ym(raw):
    try:
        year, month = raw.split("-")
        parsed = date(int(year), int(month), 1)
    except (ValueError, AttributeError):
        return None
    return parsed


def _week_key(value):
    iso = value.isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


def _quarter_of(month):
    return (month - 1) // 3 + 1


def _bucket_key_expr(grain):
    """SQL expression producing a bucket's string key from Transaction.posted_at,
    formatted to match the corresponding Python key helper below."""
    truncated = func.date_trunc(grain, Transaction.posted_at)
    if grain == "week":
        return func.to_char(truncated, 'IYYY-"W"IW')
    if grain == "quarter":
        return func.to_char(truncated, 'YYYY-"Q"Q')
    if grain == "year":
        return func.to_char(truncated, "YYYY")
    return func.to_char(truncated, "YYYY-MM")  # month


def _bucket_keys(from_month, to_month, grain):
    """The ordered list of bucket keys spanning [from_month, to_month]
    inclusive, at the given grain. Returns None if it would exceed the grain's
    cap (so a pathological range can't build a giant list before erroring)."""
    cap = _MAX_BUCKETS[grain]
    keys = []

    def _emit(key):
        if not keys or keys[-1] != key:
            keys.append(key)
        return len(keys) <= cap

    if grain == "year":
        for year in range(from_month.year, to_month.year + 1):
            if not _emit(f"{year:04d}"):
                return None
    elif grain == "quarter":
        cursor = (from_month.year, _quarter_of(from_month.month))
        last = (to_month.year, _quarter_of(to_month.month))
        while cursor <= last:
            if not _emit(f"{cursor[0]:04d}-Q{cursor[1]}"):
                return None
            cursor = (cursor[0] + 1, 1) if cursor[1] == 4 else (cursor[0], cursor[1] + 1)
    elif grain == "week":
        last_day = _add_month(to_month) - timedelta(days=1)
        cursor = from_month - timedelta(days=from_month.weekday())  # Monday of that week
        while cursor <= last_day:
            if not _emit(_week_key(cursor)):
                return None
            cursor += timedelta(days=7)
    else:  # month
        cursor = from_month
        while cursor <= to_month:
            if not _emit(f"{cursor.year:04d}-{cursor.month:02d}"):
                return None
            cursor = _add_month(cursor)

    return keys


def _parse_range(from_param, to_param, grain):
    """(start_date, end_exclusive, [bucket_key, ...]) on success, or
    (None, None, error_message)."""
    to_month = _first_of_month(date.today()) if not to_param else _parse_ym(to_param)
    if to_month is None:
        return None, None, "to must be a YYYY-MM value"

    if from_param:
        from_month = _parse_ym(from_param)
        if from_month is None:
            return None, None, "from must be a YYYY-MM value"
    else:
        from_month = to_month
        for _ in range(_DEFAULT_RANGE_MONTHS - 1):
            from_month = _sub_month(from_month)

    if from_month > to_month:
        return None, None, "from must not be after to"

    buckets = _bucket_keys(from_month, to_month, grain)
    if buckets is None:
        return None, None, f"range must be at most {_MAX_BUCKETS[grain]} {grain} buckets"

    return from_month, _add_month(to_month), buckets


def _parse_id_list(raw):
    """A comma-separated list of positive ints, or None if the param is
    absent, and (False) to signal a malformed value the caller turns into 400."""
    if raw is None:
        return None
    try:
        ids = [int(part) for part in raw.split(",") if part != ""]
    except ValueError:
        return False
    if not ids or any(i <= 0 for i in ids):
        return False
    return ids


def _money(value):
    """Always two decimal places, matching the Numeric(12,2) money columns
    everywhere else in this app."""
    return str((value if value is not None else _ZERO).quantize(_CENTS))


def _resolve_account_filter(raw, user_id):
    """(list_of_ids_or_None, error_response_or_None)."""
    ids = _parse_id_list(raw)
    if ids is None:
        return None, None
    if ids is False:
        return None, (jsonify({"error": "accounts must be a comma-separated list of ids"}), 400)
    owned = {a.id for a in Account.query.filter_by(user_id=user_id).all()}
    if not set(ids).issubset(owned):
        return None, (jsonify({"error": "unknown account id"}), 400)
    return ids, None


def _resolve_category_filter(raw, user_id):
    """(requested_ids_or_None, effective_id_set_or_None, error_response_or_None).
    A group id (a category with non-archived children) expands to itself plus
    its children."""
    ids = _parse_id_list(raw)
    if ids is None:
        return None, None, None
    if ids is False:
        return None, None, (jsonify({"error": "categories must be a comma-separated list of ids"}), 400)

    by_id = {c.id: c for c in Category.query.filter_by(user_id=user_id).all()}
    if not set(ids).issubset(by_id):
        return None, None, (jsonify({"error": "unknown category id"}), 400)

    children_by_parent = {}
    for c in by_id.values():
        if c.parent_id is not None and not c.archived:
            children_by_parent.setdefault(c.parent_id, []).append(c.id)

    effective = set()
    for cid in ids:
        effective.add(cid)
        effective.update(children_by_parent.get(cid, []))
    return ids, effective, None


@reports_bp.route("/reports", methods=["GET"])
@jwt_required()
def get_reports():
    user_id = current_user_id()

    grain = request.args.get("grain", _DEFAULT_GRAIN)
    if grain not in _GRAINS:
        return jsonify({"error": f"grain must be one of {', '.join(_GRAINS)}"}), 400

    start, end, buckets_or_error = _parse_range(request.args.get("from"), request.args.get("to"), grain)
    if start is None:
        return jsonify({"error": buckets_or_error}), 400
    buckets = buckets_or_error

    account_ids, error = _resolve_account_filter(request.args.get("accounts"), user_id)
    if error:
        return error
    category_ids, category_id_set, error = _resolve_category_filter(request.args.get("categories"), user_id)
    if error:
        return error

    exclude_transfers = request.args.get("exclude_transfers", "true").lower() != "false"

    bucket_expr = _bucket_key_expr(grain)
    expense_expr = case((Transaction.amount < 0, -Transaction.amount), else_=0)

    extra_filters = []
    if account_ids is not None:
        extra_filters.append(Transaction.account_id.in_(account_ids))
    if category_id_set is not None:
        extra_filters.append(Transaction.category_id.in_(category_id_set))
    if exclude_transfers:
        extra_filters.append(Transaction.transfer.is_(False))

    def _q(*columns):
        return (
            db.session.query(*columns)
            .join(Account, Transaction.account_id == Account.id)
            .filter(
                Account.user_id == user_id,
                Transaction.posted_at >= start,
                Transaction.posted_at < end,
                *extra_filters,
            )
        )

    # ---- spending by category (per bucket, expense only) ------------------
    category_meta = {row.id: row for row in Category.query.filter_by(user_id=user_id).all()}
    spend_rows = (
        _q(
            Transaction.category_id,
            bucket_expr.label("b"),
            func.sum(expense_expr).label("amount"),
        )
        .filter(Transaction.amount < 0)
        .group_by(Transaction.category_id, "b")
        .all()
    )
    by_category = {}  # category_id (or None) -> {bucket_key: Decimal}
    for row in spend_rows:
        by_category.setdefault(row.category_id, {})[row.b] = row.amount or _ZERO

    spending_by_category = []
    for category_id, per_bucket in sorted(
        by_category.items(),
        key=lambda kv: sum(kv[1].values()),
        reverse=True,
    ):
        meta = category_meta.get(category_id)
        spending_by_category.append(
            {
                "category_id": category_id,
                "category": meta.name if meta else "Uncategorized",
                "parent_id": meta.parent_id if meta else None,
                "total": _money(sum(per_bucket.values(), _ZERO)),
                "by_bucket": [
                    {"bucket": key, "amount": _money(per_bucket.get(key, _ZERO))} for key in buckets
                ],
            }
        )

    # ---- income vs expense (per bucket) --------------------------------
    ie_rows = (
        _q(
            bucket_expr.label("b"),
            func.sum(case((Transaction.is_income.is_(True), Transaction.amount), else_=0)).label("income"),
            func.sum(expense_expr).label("expense"),
            func.sum(Transaction.amount).label("net"),
        )
        .group_by("b")
        .all()
    )
    ie_by_bucket = {row.b: row for row in ie_rows}
    income_vs_expense = []
    period_over_period_spend = []
    previous_expense = None
    for key in buckets:
        row = ie_by_bucket.get(key)
        income = row.income if row and row.income is not None else _ZERO
        expense = row.expense if row and row.expense is not None else _ZERO
        net = row.net if row and row.net is not None else _ZERO
        income_vs_expense.append(
            {"bucket": key, "income": _money(income), "expense": _money(expense), "net": _money(net)}
        )

        change = None if previous_expense is None else expense - previous_expense
        change_pct = None
        if previous_expense not in (None, _ZERO):
            change_pct = str((change / previous_expense).quantize(Decimal("0.0001")))
        period_over_period_spend.append(
            {
                "bucket": key,
                "total": _money(expense),
                "change": None if change is None else _money(change),
                "change_pct": change_pct,
            }
        )
        previous_expense = expense

    # ---- top merchants (expense only, whole range) ----------------------
    merchant_rows = (
        _q(
            Transaction.description,
            func.sum(expense_expr).label("total"),
            func.count().label("count"),
        )
        .filter(Transaction.amount < 0)
        .group_by(Transaction.description)
        .order_by(func.sum(expense_expr).desc())
        .limit(_TOP_MERCHANTS)
        .all()
    )
    top_merchants = [
        {"description": row.description, "total": _money(row.total), "count": row.count}
        for row in merchant_rows
    ]

    return jsonify(
        {
            "from": buckets[0],
            "to": buckets[-1],
            "grain": grain,
            "buckets": buckets,
            "filters": {
                "accounts": account_ids or [],
                "categories": category_ids or [],
                "grain": grain,
                "exclude_transfers": exclude_transfers,
            },
            "spending_by_category": spending_by_category,
            "income_vs_expense": income_vs_expense,
            "month_over_month_spend": period_over_period_spend,
            "top_merchants": top_merchants,
        }
    ), 200
