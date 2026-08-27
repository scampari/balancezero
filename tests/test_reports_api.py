"""Integration tests for spec/reports-api.md — GET /api/reports.

Pure pytest against real Postgres, seeding rows directly (same style as
tests/test_budget_api.py).
"""

from datetime import date

import pytest
from models import Account, Category, Transaction, db


def _seed(user, rows):
    """rows: list of (posted_at 'YYYY-MM-DD', amount, description, is_income,
    category_id)."""
    account = Account(user_id=user.id, name="Checking")
    db.session.add(account)
    db.session.flush()
    for posted_at, amount, description, is_income, category_id in rows:
        db.session.add(
            Transaction(
                account_id=account.id,
                posted_at=date.fromisoformat(posted_at),
                amount=amount,
                description=description,
                is_income=is_income,
                category_id=category_id,
            )
        )
    db.session.commit()
    return account


@pytest.fixture()
def groceries(client, test_user):
    category = Category(user_id=test_user.id, name="Groceries")
    db.session.add(category)
    db.session.commit()
    return category


# ---------------------------------------------------------------------------
# range parsing
# ---------------------------------------------------------------------------


def test_reports_requires_auth(client):
    assert client.get("/api/reports").status_code == 401


def test_reports_defaults_to_last_six_months(client, test_user, auth_headers):
    body = client.get("/api/reports", headers=auth_headers).get_json()
    assert len(body["months"]) == 6
    assert body["from"] == body["months"][0]
    assert body["to"] == body["months"][-1]


def test_reports_respects_explicit_range(client, test_user, auth_headers):
    body = client.get("/api/reports?from=2026-01&to=2026-03", headers=auth_headers).get_json()
    assert body["months"] == ["2026-01", "2026-02", "2026-03"]


def test_reports_invalid_from_returns_400(client, test_user, auth_headers):
    assert client.get("/api/reports?from=nonsense", headers=auth_headers).status_code == 400


def test_reports_from_after_to_returns_400(client, test_user, auth_headers):
    assert client.get("/api/reports?from=2026-06&to=2026-01", headers=auth_headers).status_code == 400


def test_reports_range_too_large_returns_400(client, test_user, auth_headers):
    assert client.get("/api/reports?from=2020-01&to=2026-01", headers=auth_headers).status_code == 400


def test_reports_empty_user_gets_zero_filled_arrays(client, test_user, auth_headers):
    body = client.get("/api/reports?from=2026-01&to=2026-02", headers=auth_headers).get_json()
    assert body["spending_by_category"] == []
    assert body["top_merchants"] == []
    assert [m["expense"] for m in body["income_vs_expense"]] == ["0.00", "0.00"]
    assert body["month_over_month_spend"][0]["change"] is None


# ---------------------------------------------------------------------------
# datasets
# ---------------------------------------------------------------------------


def test_spending_by_category_totals_and_monthly_breakdown(client, test_user, auth_headers, groceries):
    _seed(
        test_user,
        [
            ("2026-01-05", -100, "Store A", False, groceries.id),
            ("2026-02-10", -40, "Store B", False, groceries.id),
        ],
    )

    body = client.get("/api/reports?from=2026-01&to=2026-03", headers=auth_headers).get_json()
    row = next(r for r in body["spending_by_category"] if r["category_id"] == groceries.id)
    assert row["category"] == "Groceries"
    assert row["total"] == "140.00"
    assert [m["amount"] for m in row["by_month"]] == ["100.00", "40.00", "0.00"]  # zero-filled, in order


def test_spending_by_category_has_uncategorized_bucket(client, test_user, auth_headers):
    _seed(test_user, [("2026-02-01", -25, "Mystery", False, None)])
    body = client.get("/api/reports?from=2026-02&to=2026-02", headers=auth_headers).get_json()
    bucket = next(r for r in body["spending_by_category"] if r["category_id"] is None)
    assert bucket["category"] == "Uncategorized"
    assert bucket["total"] == "25.00"


def test_income_vs_expense_per_month(client, test_user, auth_headers):
    _seed(
        test_user,
        [
            ("2026-02-01", 3000, "Payroll", True, None),
            ("2026-02-15", -1200, "Rent", False, None),
            ("2026-02-20", 50, "Refund", False, None),  # non-income inflow: nets, not "income"
        ],
    )
    body = client.get("/api/reports?from=2026-02&to=2026-02", headers=auth_headers).get_json()
    feb = body["income_vs_expense"][0]
    assert feb["income"] == "3000.00"
    assert feb["expense"] == "1200.00"
    assert feb["net"] == "1850.00"  # 3000 - 1200 + 50


def test_month_over_month_change_and_pct(client, test_user, auth_headers):
    _seed(
        test_user,
        [
            ("2026-01-10", -1000, "Jan spend", False, None),
            ("2026-02-10", -1250, "Feb spend", False, None),
        ],
    )
    body = client.get("/api/reports?from=2026-01&to=2026-02", headers=auth_headers).get_json()
    jan, feb = body["month_over_month_spend"]
    assert jan["change"] is None and jan["change_pct"] is None
    assert feb["change"] == "250.00"
    assert feb["change_pct"] == "0.2500"


def test_top_merchants_grouped_expense_only_and_capped(client, test_user, auth_headers):
    _seed(
        test_user,
        [
            ("2026-02-01", -30, "AMAZON", False, None),
            ("2026-02-05", -20, "AMAZON", False, None),
            ("2026-02-08", -10, "CORNER STORE", False, None),
            ("2026-02-09", 500, "AMAZON", True, None),  # income — excluded
        ],
    )
    body = client.get("/api/reports?from=2026-02&to=2026-02", headers=auth_headers).get_json()
    merchants = {m["description"]: m for m in body["top_merchants"]}
    assert merchants["AMAZON"]["total"] == "50.00"
    assert merchants["AMAZON"]["count"] == 2
    assert len(body["top_merchants"]) <= 10


def test_reports_isolated_per_user(client, test_user, auth_headers, groceries):
    from werkzeug.security import generate_password_hash
    from models import User

    other = User(username="other", password_hash=generate_password_hash("x" * 12))
    db.session.add(other)
    db.session.flush()
    _seed(other, [("2026-02-01", -999, "Their spend", False, None)])

    body = client.get("/api/reports?from=2026-02&to=2026-02", headers=auth_headers).get_json()
    assert body["spending_by_category"] == []


def test_reports_money_values_are_strings(client, test_user, auth_headers):
    _seed(test_user, [("2026-02-01", -12.34, "X", False, None)])
    body = client.get("/api/reports?from=2026-02&to=2026-02", headers=auth_headers).get_json()
    assert body["income_vs_expense"][0]["expense"] == "12.34"
    assert isinstance(body["top_merchants"][0]["total"], str)


def test_demo_user_can_view_reports(client, demo_user, demo_auth_headers):
    assert client.get("/api/reports?from=2026-02&to=2026-02", headers=demo_auth_headers).status_code == 200
