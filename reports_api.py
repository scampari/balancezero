"""Spending-habits reporting — one read-only endpoint that returns every
dataset the /reports page renders. Aggregation only; no migration.

Sign/definitions, consistent with budget_api:
  expense  = SUM(-amount) WHERE amount < 0   (reported as a positive number)
  income   = SUM(amount)  WHERE is_income
  net      = SUM(amount)  over every transaction that month (signed:
             + inflow, - outflow) — so a non-income refund nets in here only.
Grouping uses date_trunc / to_char — Postgres, which is prod and the test DB.
"""

from datetime import date
from decimal import Decimal

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import case, func

from api_helpers import current_user_id
from models import Account, Category, Transaction, db

reports_bp = Blueprint("reports_api", __name__, url_prefix="/api")

_MAX_RANGE_MONTHS = 24
_DEFAULT_RANGE_MONTHS = 6
_TOP_MERCHANTS = 10
_ZERO = Decimal("0")
_CENTS = Decimal("0.01")


def _first_of_month(value):
    return value.replace(day=1)


def _add_month(value):
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def _sub_month(value):
    return date(value.year - 1, 12, 1) if value.month == 1 else date(value.year, value.month - 1, 1)


def _month_key(value):
    return f"{value.year:04d}-{value.month:02d}"


def _parse_ym(raw):
    try:
        year, month = raw.split("-")
        parsed = date(int(year), int(month), 1)
    except (ValueError, AttributeError):
        return None
    return parsed


def _parse_range(from_param, to_param):
    """(start_date, end_exclusive, [month_key, ...]) on success, or
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

    span = (to_month.year - from_month.year) * 12 + (to_month.month - from_month.month) + 1
    if span > _MAX_RANGE_MONTHS:
        return None, None, f"range must be at most {_MAX_RANGE_MONTHS} months"

    months = []
    cursor = from_month
    while cursor <= to_month:
        months.append(_month_key(cursor))
        cursor = _add_month(cursor)
    return from_month, _add_month(to_month), months


def _money(value):
    """Always two decimal places, matching the Numeric(12,2) money columns
    everywhere else in this app."""
    return str((value if value is not None else _ZERO).quantize(_CENTS))


@reports_bp.route("/reports", methods=["GET"])
@jwt_required()
def get_reports():
    start, end, months_or_error = _parse_range(request.args.get("from"), request.args.get("to"))
    if start is None:
        return jsonify({"error": months_or_error}), 400
    months = months_or_error
    user_id = current_user_id()

    month_expr = func.to_char(func.date_trunc("month", Transaction.posted_at), "YYYY-MM")
    expense_expr = case((Transaction.amount < 0, -Transaction.amount), else_=0)

    def _q(*columns):
        return (
            db.session.query(*columns)
            .join(Account, Transaction.account_id == Account.id)
            .filter(
                Account.user_id == user_id,
                Transaction.posted_at >= start,
                Transaction.posted_at < end,
            )
        )

    # ---- spending by category (per month, expense only) --------------------
    category_meta = {row.id: row for row in Category.query.filter_by(user_id=user_id).all()}
    spend_rows = (
        _q(
            Transaction.category_id,
            month_expr.label("m"),
            func.sum(expense_expr).label("amount"),
        )
        .filter(Transaction.amount < 0)
        .group_by(Transaction.category_id, "m")
        .all()
    )
    by_category = {}  # category_id (or None) -> {month_key: Decimal}
    for row in spend_rows:
        by_category.setdefault(row.category_id, {})[row.m] = row.amount or _ZERO

    spending_by_category = []
    for category_id, per_month in sorted(
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
                "total": _money(sum(per_month.values(), _ZERO)),
                "by_month": [
                    {"month": key, "amount": _money(per_month.get(key, _ZERO))} for key in months
                ],
            }
        )

    # ---- income vs expense (per month) -----------------------------------
    ie_rows = (
        _q(
            month_expr.label("m"),
            func.sum(case((Transaction.is_income.is_(True), Transaction.amount), else_=0)).label("income"),
            func.sum(expense_expr).label("expense"),
            func.sum(Transaction.amount).label("net"),
        )
        .group_by("m")
        .all()
    )
    ie_by_month = {row.m: row for row in ie_rows}
    income_vs_expense = []
    month_over_month_spend = []
    previous_expense = None
    for key in months:
        row = ie_by_month.get(key)
        income = row.income if row and row.income is not None else _ZERO
        expense = row.expense if row and row.expense is not None else _ZERO
        net = row.net if row and row.net is not None else _ZERO
        income_vs_expense.append(
            {"month": key, "income": _money(income), "expense": _money(expense), "net": _money(net)}
        )

        change = None if previous_expense is None else expense - previous_expense
        change_pct = None
        if previous_expense not in (None, _ZERO):
            change_pct = str((change / previous_expense).quantize(Decimal("0.0001")))
        month_over_month_spend.append(
            {
                "month": key,
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
            "from": months[0],
            "to": months[-1],
            "months": months,
            "spending_by_category": spending_by_category,
            "income_vs_expense": income_vs_expense,
            "month_over_month_spend": month_over_month_spend,
            "top_merchants": top_merchants,
        }
    ), 200
