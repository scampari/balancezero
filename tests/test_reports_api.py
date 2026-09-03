"""Integration tests for spec/reports-api.md — GET /api/reports.

Pure pytest against real Postgres, seeding rows directly (same style as
tests/test_budget_api.py).
"""

from datetime import date

import pytest
from models import Account, Category, Transaction, db


def _seed(user, rows, account_name="Checking", transfer_descriptions=()):
    """rows: list of (posted_at 'YYYY-MM-DD', amount, description, is_income,
    category_id). A description in `transfer_descriptions` is flagged as a
    transfer."""
    account = Account(user_id=user.id, name=account_name)
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
                transfer=description in transfer_descriptions,
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
    assert len(body["buckets"]) == 6
    assert body["from"] == body["buckets"][0]
    assert body["to"] == body["buckets"][-1]
    assert body["grain"] == "month"


def test_reports_respects_explicit_range(client, test_user, auth_headers):
    body = client.get("/api/reports?from=2026-01&to=2026-03", headers=auth_headers).get_json()
    assert body["buckets"] == ["2026-01", "2026-02", "2026-03"]


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


def test_spending_by_category_totals_and_bucket_breakdown(client, test_user, auth_headers, groceries):
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
    assert [m["amount"] for m in row["by_bucket"]] == ["100.00", "40.00", "0.00"]  # zero-filled, in order


def test_spending_by_category_has_uncategorized_bucket(client, test_user, auth_headers):
    _seed(test_user, [("2026-02-01", -25, "Mystery", False, None)])
    body = client.get("/api/reports?from=2026-02&to=2026-02", headers=auth_headers).get_json()
    bucket = next(r for r in body["spending_by_category"] if r["category_id"] is None)
    assert bucket["category"] == "Uncategorized"
    assert bucket["total"] == "25.00"


def test_income_vs_expense_per_bucket(client, test_user, auth_headers):
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
    assert feb["bucket"] == "2026-02"
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


# ---------------------------------------------------------------------------
# grain (changes/020)
# ---------------------------------------------------------------------------


def test_reports_invalid_grain_returns_400(client, test_user, auth_headers):
    assert client.get("/api/reports?grain=fortnight", headers=auth_headers).status_code == 400


def test_reports_grain_year_buckets(client, test_user, auth_headers):
    _seed(
        test_user,
        [
            ("2025-04-01", -100, "A", False, None),
            ("2026-04-01", -200, "B", False, None),
        ],
    )
    body = client.get("/api/reports?from=2025-01&to=2026-06&grain=year", headers=auth_headers).get_json()
    assert body["grain"] == "year"
    assert body["buckets"] == ["2025", "2026"]
    assert [m["expense"] for m in body["income_vs_expense"]] == ["100.00", "200.00"]


def test_reports_grain_quarter_buckets(client, test_user, auth_headers):
    body = client.get("/api/reports?from=2026-01&to=2026-09&grain=quarter", headers=auth_headers).get_json()
    assert body["buckets"] == ["2026-Q1", "2026-Q2", "2026-Q3"]


def test_reports_grain_week_buckets_and_key_format(client, test_user, auth_headers):
    _seed(test_user, [("2026-08-19", -50, "Midweek", False, None)])
    body = client.get("/api/reports?from=2026-08&to=2026-08&grain=week", headers=auth_headers).get_json()
    assert body["grain"] == "week"
    assert all(key.count("-W") == 1 for key in body["buckets"])
    # 2026-08-19 falls in ISO week 34.
    hit = next(m for m in body["income_vs_expense"] if m["expense"] == "50.00")
    assert hit["bucket"] == "2026-W34"


def test_reports_grain_bucket_cap_returns_400(client, test_user, auth_headers):
    # 13 months of weekly buckets is well over the 53-week cap? No — ~56 weeks.
    assert client.get("/api/reports?from=2025-01&to=2026-03&grain=week", headers=auth_headers).status_code == 400


# ---------------------------------------------------------------------------
# account + category filters, transfer exclusion (changes/020)
# ---------------------------------------------------------------------------


def test_reports_accounts_filter_scopes_every_panel(client, test_user, auth_headers):
    keep = _seed(test_user, [("2026-02-01", -100, "KEEP", False, None)], account_name="Keep")
    _seed(test_user, [("2026-02-01", -999, "DROP", False, None)], account_name="Drop")

    body = client.get(
        f"/api/reports?from=2026-02&to=2026-02&accounts={keep.id}", headers=auth_headers
    ).get_json()
    assert body["filters"]["accounts"] == [keep.id]
    assert [m["description"] for m in body["top_merchants"]] == ["KEEP"]
    assert body["income_vs_expense"][0]["expense"] == "100.00"


def test_reports_unknown_account_id_returns_400(client, test_user, auth_headers):
    assert client.get("/api/reports?accounts=999999", headers=auth_headers).status_code == 400


def test_reports_categories_filter_expands_a_group_to_its_children(client, test_user, auth_headers):
    parent = Category(user_id=test_user.id, name="Food")
    db.session.add(parent)
    db.session.flush()
    child = Category(user_id=test_user.id, name="Groceries", parent_id=parent.id)
    other = Category(user_id=test_user.id, name="Rent")
    db.session.add_all([child, other])
    db.session.commit()

    _seed(
        test_user,
        [
            ("2026-02-01", -60, "WHOLE FOODS", False, child.id),
            ("2026-02-02", -1500, "LANDLORD", False, other.id),
        ],
    )

    body = client.get(
        f"/api/reports?from=2026-02&to=2026-02&categories={parent.id}", headers=auth_headers
    ).get_json()
    assert body["filters"]["categories"] == [parent.id]
    merchants = {m["description"] for m in body["top_merchants"]}
    assert merchants == {"WHOLE FOODS"}  # Rent excluded


def test_reports_excludes_transfers_by_default_and_includes_on_request(client, test_user, auth_headers):
    _seed(
        test_user,
        [
            ("2026-02-01", -40, "COFFEE", False, None),
            ("2026-02-02", -300, "TO SAVINGS", False, None),
        ],
        transfer_descriptions=("TO SAVINGS",),
    )

    default = client.get("/api/reports?from=2026-02&to=2026-02", headers=auth_headers).get_json()
    assert default["filters"]["exclude_transfers"] is True
    assert default["income_vs_expense"][0]["expense"] == "40.00"  # transfer dropped

    included = client.get(
        "/api/reports?from=2026-02&to=2026-02&exclude_transfers=false", headers=auth_headers
    ).get_json()
    assert included["filters"]["exclude_transfers"] is False
    assert included["income_vs_expense"][0]["expense"] == "340.00"


def test_reports_echoes_grain_in_filters(client, test_user, auth_headers):
    body = client.get("/api/reports?grain=quarter", headers=auth_headers).get_json()
    assert body["filters"]["grain"] == "quarter"


# ---------------------------------------------------------------------------
# exclude_transfers only hides UNCATEGORIZED transfers (changes/029).
# Traces to spec/reports-api.md § "exclude_transfers cases (changes/029)".
# ---------------------------------------------------------------------------


def test_reports_default_includes_a_categorized_transfer(client, test_user, auth_headers, groceries):
    # Arrange — two transfers: one filed under Groceries, one loose.
    _seed(
        test_user,
        [
            ("2026-02-01", -40, "COFFEE", False, None),
            ("2026-02-02", -100, "VENMO RENT SPLIT", False, groceries.id),
            ("2026-02-03", -300, "TO SAVINGS", False, None),
        ],
        transfer_descriptions=("VENMO RENT SPLIT", "TO SAVINGS"),
    )

    body = client.get("/api/reports?from=2026-02&to=2026-02", headers=auth_headers).get_json()

    # The categorized transfer counts as spend; the uncategorized one does not.
    assert body["filters"]["exclude_transfers"] is True
    assert body["income_vs_expense"][0]["expense"] == "140.00"  # 40 coffee + 100 categorized transfer
    by_cat = {row["category"]: row["total"] for row in body["spending_by_category"]}
    assert by_cat.get("Groceries") == "100.00"
    merchants = {m["description"] for m in body["top_merchants"]}
    assert "VENMO RENT SPLIT" in merchants
    assert "TO SAVINGS" not in merchants


# Spec cases 2 (uncategorized transfer still excluded by default) and 3
# (exclude_transfers=false includes everything) are "unchanged from 020" and
# already pinned by test_reports_excludes_transfers_by_default_and_includes_on_request.
