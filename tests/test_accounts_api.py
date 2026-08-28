"""Integration tests for spec/accounts-api.md — list connected bank accounts.

Every test here traces to a case in spec/accounts-api.md's integration
test contract. Do not add cases here that aren't in the spec — extend the
spec first.
"""

from datetime import datetime
from decimal import Decimal

from models import Account, User, db
from werkzeug.security import generate_password_hash


def _make_account(user_id, name="Checking", balance="500.00", plaid_account_id=None,
                  type="depository", subtype="checking"):
    account = Account(
        user_id=user_id,
        name=name,
        type=type,
        subtype=subtype,
        currency="USD",
        balance=Decimal(balance),
        available_balance=Decimal(balance),
        balance_date=datetime.utcnow(),
        plaid_account_id=plaid_account_id,
    )
    db.session.add(account)
    db.session.commit()
    return account


# ---------------------------------------------------------------------------
# GET /api/accounts
# ---------------------------------------------------------------------------


def test_list_accounts_returns_own_accounts(client, test_user, auth_headers):
    # Arrange
    _make_account(test_user.id, name="Checking", balance="1234.56")

    # Act
    response = client.get("/api/accounts", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert len(body["accounts"]) == 1
    account = body["accounts"][0]
    assert account["name"] == "Checking"
    assert account["balance"] == "1234.56"
    assert account["currency"] == "USD"
    assert "available_balance" in account
    assert "balance_date" in account


def test_list_accounts_only_shows_own_accounts(client, test_user, auth_headers):
    # Arrange — another user's account
    other_user = User(username="accounts-other", password_hash=generate_password_hash("irrelevant"))
    db.session.add(other_user)
    db.session.commit()
    _make_account(other_user.id, name="NotYours")
    _make_account(test_user.id, name="Yours")

    # Act
    response = client.get("/api/accounts", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    names = [a["name"] for a in response.get_json()["accounts"]]
    assert names == ["Yours"]


def test_list_accounts_without_token_returns_401(client, test_user):
    # Act
    response = client.get("/api/accounts")

    # Assert
    assert response.status_code == 401


def test_list_accounts_includes_type_and_subtype(client, test_user, auth_headers):
    # Arrange
    _make_account(test_user.id, name="Rewards Card", type="credit", subtype="credit card")

    # Act
    response = client.get("/api/accounts", headers=auth_headers)

    # Assert
    account = response.get_json()["accounts"][0]
    assert account["type"] == "credit"
    assert account["subtype"] == "credit card"


def test_list_accounts_excludes_plaid_account_id(client, test_user, auth_headers):
    # Arrange
    _make_account(test_user.id, plaid_account_id="plaid-internal-id-should-not-leak")

    # Act
    response = client.get("/api/accounts", headers=auth_headers)

    # Assert
    body = response.get_json()
    assert "plaid_account_id" not in body["accounts"][0]
