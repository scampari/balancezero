"""Integration tests for spec/transactions.md — list + categorize transactions.

Every test here traces to a case in spec/transactions.md's integration test contract.
Do not add cases here that aren't in the spec — extend the spec first.
"""

from datetime import date
from decimal import Decimal

from conftest import TEST_USERNAME, TEST_PASSWORD
from models import Account, Category, Transaction, User, db
from werkzeug.security import generate_password_hash

CURRENT_MONTH = date.today().replace(day=1)
LAST_MONTH = date(CURRENT_MONTH.year - 1, 12, 1) if CURRENT_MONTH.month == 1 else date(CURRENT_MONTH.year, CURRENT_MONTH.month - 1, 1)


def _make_account(user_id, name="Checking"):
    account = Account(user_id=user_id, name=name)
    db.session.add(account)
    db.session.commit()
    return account


def _make_category(user_id, name="Groceries"):
    category = Category(user_id=user_id, name=name)
    db.session.add(category)
    db.session.commit()
    return category


def _make_transaction(account_id, posted_at, amount, description, category_id=None, pending=False):
    txn = Transaction(
        account_id=account_id,
        category_id=category_id,
        posted_at=posted_at,
        amount=Decimal(amount),
        description=description,
        pending=pending,
    )
    db.session.add(txn)
    db.session.commit()
    return txn


# ---------------------------------------------------------------------------
# GET /api/transactions
# ---------------------------------------------------------------------------


def test_list_transactions_returns_current_month_for_authenticated_user(client, test_user, auth_headers):
    # Arrange
    account = _make_account(test_user.id)
    category = _make_category(test_user.id)
    this_month_txn = _make_transaction(account.id, CURRENT_MONTH, "-42.50", "Grocery run", category_id=category.id)
    _make_transaction(account.id, LAST_MONTH, "-10.00", "Old purchase")

    # Act
    response = client.get("/api/transactions", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body["month"] == CURRENT_MONTH.isoformat()
    ids = [t["id"] for t in body["transactions"]]
    assert this_month_txn.id in ids
    matching = next(t for t in body["transactions"] if t["id"] == this_month_txn.id)
    assert matching["category_id"] == category.id
    assert matching["category_name"] == "Groceries"
    assert matching["amount"] == "-42.50"
    assert matching["description"] == "Grocery run"
    # last month's transaction must not appear
    assert all(t["posted_at"].startswith(CURRENT_MONTH.isoformat()[:7]) for t in body["transactions"])


def test_list_transactions_shows_null_category_for_uncategorized(client, test_user, auth_headers):
    # Arrange
    account = _make_account(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "-15.00", "Uncategorized thing")

    # Act
    response = client.get("/api/transactions", headers=auth_headers)

    # Assert
    matching = next(t for t in response.get_json()["transactions"] if t["id"] == txn.id)
    assert matching["category_id"] is None
    assert matching["category_name"] is None


def test_list_transactions_with_explicit_month_param(client, test_user, auth_headers):
    # Arrange
    account = _make_account(test_user.id)
    last_month_txn = _make_transaction(account.id, LAST_MONTH, "-5.00", "Last month thing")

    # Act
    response = client.get(f"/api/transactions?month={LAST_MONTH.isoformat()}", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body["month"] == LAST_MONTH.isoformat()
    assert any(t["id"] == last_month_txn.id for t in body["transactions"])


def test_list_transactions_only_shows_own_accounts(client, test_user, auth_headers):
    # Arrange — another user's transaction
    other_user = User(username="txn-other", password_hash=generate_password_hash("irrelevant"))
    db.session.add(other_user)
    db.session.commit()
    other_account = _make_account(other_user.id, name="NotYours")
    _make_transaction(other_account.id, CURRENT_MONTH, "-1.00", "Not yours")

    # Act
    response = client.get("/api/transactions", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    descriptions = [t["description"] for t in response.get_json()["transactions"]]
    assert "Not yours" not in descriptions


def test_list_transactions_without_token_returns_401(client, test_user):
    # Act
    response = client.get("/api/transactions")

    # Assert
    assert response.status_code == 401


def test_list_transactions_invalid_month_returns_400(client, test_user, auth_headers):
    # Act
    response = client.get("/api/transactions?month=not-a-date", headers=auth_headers)

    # Assert
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# PATCH /api/transactions/<id>
# ---------------------------------------------------------------------------


def test_patch_transaction_assigns_category(client, test_user, auth_headers):
    # Arrange
    account = _make_account(test_user.id)
    category = _make_category(test_user.id, name="Dining")
    txn = _make_transaction(account.id, CURRENT_MONTH, "-20.00", "Restaurant")

    # Act
    response = client.patch(
        f"/api/transactions/{txn.id}", json={"category_id": category.id}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body["category_id"] == category.id
    assert body["category_name"] == "Dining"

    # Assert side effect
    db.session.refresh(txn)
    assert txn.category_id == category.id


def test_patch_transaction_uncategorizes_with_null(client, test_user, auth_headers):
    # Arrange
    account = _make_account(test_user.id)
    category = _make_category(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "-20.00", "Something", category_id=category.id)

    # Act
    response = client.patch(f"/api/transactions/{txn.id}", json={"category_id": None}, headers=auth_headers)

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body["category_id"] is None
    assert body["category_name"] is None
    db.session.refresh(txn)
    assert txn.category_id is None


def test_patch_transaction_without_token_returns_401(client, test_user, auth_headers):
    # Arrange
    account = _make_account(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "-20.00", "Something")

    # Act
    response = client.patch(f"/api/transactions/{txn.id}", json={"category_id": None})

    # Assert
    assert response.status_code == 401


def test_patch_transaction_missing_category_id_key_returns_400(client, test_user, auth_headers):
    # Arrange
    account = _make_account(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "-20.00", "Something")

    # Act
    response = client.patch(f"/api/transactions/{txn.id}", json={}, headers=auth_headers)

    # Assert
    assert response.status_code == 400


def test_patch_nonexistent_transaction_returns_404(client, test_user, auth_headers):
    # Act
    response = client.patch("/api/transactions/999999", json={"category_id": None}, headers=auth_headers)

    # Assert
    assert response.status_code == 404


def test_patch_another_users_transaction_returns_403(client, test_user, auth_headers):
    # Arrange
    other_user = User(username="txn-other2", password_hash=generate_password_hash("irrelevant"))
    db.session.add(other_user)
    db.session.commit()
    other_account = _make_account(other_user.id, name="NotYours")
    other_txn = _make_transaction(other_account.id, CURRENT_MONTH, "-1.00", "Not yours")

    # Act
    response = client.patch(
        f"/api/transactions/{other_txn.id}", json={"category_id": None}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 403


def test_patch_transaction_with_nonexistent_category_returns_404(client, test_user, auth_headers):
    # Arrange
    account = _make_account(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "-20.00", "Something")

    # Act
    response = client.patch(f"/api/transactions/{txn.id}", json={"category_id": 999999}, headers=auth_headers)

    # Assert
    assert response.status_code == 404


def test_patch_transaction_with_another_users_category_returns_403(client, test_user, auth_headers):
    # Arrange
    account = _make_account(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "-20.00", "Something")
    other_user = User(username="txn-other3", password_hash=generate_password_hash("irrelevant"))
    db.session.add(other_user)
    db.session.commit()
    other_category = _make_category(other_user.id, name="NotYours")

    # Act
    response = client.patch(
        f"/api/transactions/{txn.id}", json={"category_id": other_category.id}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# is_income / "To Be Budgeted" (005 — spec/transactions.md § GET + § PATCH)
# ---------------------------------------------------------------------------


def test_list_transactions_includes_is_income_false_for_normal_transaction(client, test_user, auth_headers):
    # Arrange — a plain categorized transaction, nothing marked "To Be Budgeted"
    account = _make_account(test_user.id)
    category = _make_category(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "-12.00", "Normal", category_id=category.id)

    # Act
    response = client.get("/api/transactions", headers=auth_headers)

    # Assert — response shape gained is_income, false for any categorized/normal row
    assert response.status_code == 200
    matching = next(t for t in response.get_json()["transactions"] if t["id"] == txn.id)
    assert "is_income" in matching
    assert matching["is_income"] is False


def test_list_transactions_shows_is_income_true_for_tbb_transaction(client, test_user, auth_headers):
    # Arrange — a transaction explicitly marked "To Be Budgeted"
    account = _make_account(test_user.id)
    txn = Transaction(
        account_id=account.id,
        category_id=None,
        posted_at=CURRENT_MONTH,
        amount=Decimal("1000.00"),
        description="Paycheck",
        is_income=True,
    )
    db.session.add(txn)
    db.session.commit()

    # Act
    response = client.get("/api/transactions", headers=auth_headers)

    # Assert
    matching = next(t for t in response.get_json()["transactions"] if t["id"] == txn.id)
    assert "is_income" in matching
    assert matching["is_income"] is True
    assert matching["category_id"] is None


def test_patch_transaction_marks_is_income_true(client, test_user, auth_headers):
    # Arrange
    account = _make_account(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "1000.00", "Paycheck")

    # Act
    response = client.patch(
        f"/api/transactions/{txn.id}",
        json={"is_income": True, "category_id": None},
        headers=auth_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert "is_income" in body
    assert body["is_income"] is True
    assert body["category_id"] is None
    assert body["category_name"] is None

    # Assert side effect
    db.session.refresh(txn)
    assert txn.is_income is True
    assert txn.category_id is None


def test_patch_is_income_true_clears_existing_category(client, test_user, auth_headers):
    # Arrange — a transaction that already has a category assigned
    account = _make_account(test_user.id)
    category = _make_category(test_user.id, name="Dining")
    txn = _make_transaction(account.id, CURRENT_MONTH, "-30.00", "Was dining", category_id=category.id)

    # Act — mark it "To Be Budgeted"
    response = client.patch(
        f"/api/transactions/{txn.id}",
        json={"is_income": True, "category_id": None},
        headers=auth_headers,
    )

    # Assert — setting is_income:true implicitly clears category_id
    assert response.status_code == 200
    body = response.get_json()
    assert "is_income" in body
    assert body["is_income"] is True
    assert body["category_id"] is None
    db.session.refresh(txn)
    assert txn.is_income is True
    assert txn.category_id is None


def test_patch_assigning_category_clears_is_income(client, test_user, auth_headers):
    # Arrange — a transaction already marked "To Be Budgeted"
    account = _make_account(test_user.id)
    category = _make_category(test_user.id, name="Dining")
    txn = Transaction(
        account_id=account.id,
        category_id=None,
        posted_at=CURRENT_MONTH,
        amount=Decimal("1000.00"),
        description="Paycheck",
        is_income=True,
    )
    db.session.add(txn)
    db.session.commit()

    # Act — assign a real category
    response = client.patch(
        f"/api/transactions/{txn.id}", json={"category_id": category.id}, headers=auth_headers
    )

    # Assert — setting a non-null category_id implicitly clears is_income
    assert response.status_code == 200
    body = response.get_json()
    assert "is_income" in body
    assert body["category_id"] == category.id
    assert body["is_income"] is False
    db.session.refresh(txn)
    assert txn.category_id == category.id
    assert txn.is_income is False


def test_patch_is_income_true_with_nonnull_category_returns_400(client, test_user, auth_headers):
    # Arrange
    account = _make_account(test_user.id)
    category = _make_category(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "-20.00", "Something")

    # Act — is_income:true together with a non-null category_id is mutually exclusive
    response = client.patch(
        f"/api/transactions/{txn.id}",
        json={"is_income": True, "category_id": category.id},
        headers=auth_headers,
    )

    # Assert
    assert response.status_code == 400
    db.session.refresh(txn)
    assert txn.is_income is False
    assert txn.category_id is None


def test_patch_assign_category_response_includes_is_income(client, test_user, auth_headers):
    # Arrange
    account = _make_account(test_user.id)
    category = _make_category(test_user.id, name="Dining")
    txn = _make_transaction(account.id, CURRENT_MONTH, "-20.00", "Restaurant")

    # Act
    response = client.patch(
        f"/api/transactions/{txn.id}", json={"category_id": category.id}, headers=auth_headers
    )

    # Assert — PATCH response shape gained is_income
    assert response.status_code == 200
    body = response.get_json()
    assert "is_income" in body
    assert body["is_income"] is False


# ---------------------------------------------------------------------------
# PATCH — "Uncategorized" clears "To Be Budgeted" (changes/011 bug fix)
# ---------------------------------------------------------------------------


def test_patch_category_null_clears_is_income(client, test_user, auth_headers):
    # Arrange — a transaction marked "To Be Budgeted"
    account = _make_account(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "500.00", "Paycheck")
    client.patch(f"/api/transactions/{txn.id}", json={"is_income": True, "category_id": None}, headers=auth_headers)
    db.session.refresh(txn)
    assert txn.is_income is True

    # Act — choose "Uncategorized" (category_id: null, no is_income key)
    response = client.patch(f"/api/transactions/{txn.id}", json={"category_id": None}, headers=auth_headers)

    # Assert — back to plain uncategorized, not stuck as TBB
    assert response.status_code == 200
    assert response.get_json()["is_income"] is False
    db.session.refresh(txn)
    assert txn.is_income is False
    assert txn.category_id is None


def test_patch_explicit_is_income_false_with_null_category_still_works(client, test_user, auth_headers):
    account = _make_account(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "500.00", "Paycheck")
    client.patch(f"/api/transactions/{txn.id}", json={"is_income": True, "category_id": None}, headers=auth_headers)

    response = client.patch(
        f"/api/transactions/{txn.id}", json={"is_income": False, "category_id": None}, headers=auth_headers
    )
    assert response.status_code == 200
    db.session.refresh(txn)
    assert txn.is_income is False


# ---------------------------------------------------------------------------
# POST /api/transactions — manual add
# ---------------------------------------------------------------------------


def test_create_manual_transaction(client, test_user, auth_headers):
    account = _make_account(test_user.id)
    category = _make_category(test_user.id)

    response = client.post(
        "/api/transactions",
        json={
            "account_id": account.id,
            "posted_at": CURRENT_MONTH.isoformat(),
            "amount": "-42.50",
            "description": "Cash lunch",
            "category_id": category.id,
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["description"] == "Cash lunch"
    assert body["amount"] == "-42.50"
    assert body["category_id"] == category.id
    assert body["is_income"] is False

    row = db.session.get(Transaction, body["id"])
    assert row.plaid_transaction_id is None  # manual, not from Plaid


def test_create_manual_transaction_without_category(client, test_user, auth_headers):
    account = _make_account(test_user.id)
    response = client.post(
        "/api/transactions",
        json={"account_id": account.id, "posted_at": CURRENT_MONTH.isoformat(), "amount": "10", "description": "X"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.get_json()["category_id"] is None


def test_create_manual_transaction_missing_fields_returns_400(client, test_user, auth_headers):
    account = _make_account(test_user.id)
    response = client.post(
        "/api/transactions",
        json={"account_id": account.id, "amount": "10"},  # no posted_at, no description
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_create_manual_transaction_bad_amount_returns_400(client, test_user, auth_headers):
    account = _make_account(test_user.id)
    response = client.post(
        "/api/transactions",
        json={"account_id": account.id, "posted_at": CURRENT_MONTH.isoformat(), "amount": "abc", "description": "X"},
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_create_manual_transaction_on_another_users_account_returns_403(client, test_user, auth_headers):
    other = User(username="other", password_hash=generate_password_hash("x" * 12))
    db.session.add(other)
    db.session.flush()
    their_account = _make_account(other.id)

    response = client.post(
        "/api/transactions",
        json={
            "account_id": their_account.id,
            "posted_at": CURRENT_MONTH.isoformat(),
            "amount": "10",
            "description": "X",
        },
        headers=auth_headers,
    )
    assert response.status_code == 403


def test_create_manual_transaction_without_token_returns_401(client, test_user):
    assert client.post("/api/transactions", json={}).status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/transactions/<id>
# ---------------------------------------------------------------------------


def test_delete_transaction(client, test_user, auth_headers):
    account = _make_account(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "-5.00", "Oops")

    response = client.delete(f"/api/transactions/{txn.id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json() == {"status": "deleted"}
    assert db.session.get(Transaction, txn.id) is None


def test_delete_nonexistent_transaction_returns_404(client, test_user, auth_headers):
    assert client.delete("/api/transactions/999999", headers=auth_headers).status_code == 404


def test_delete_another_users_transaction_returns_403(client, test_user, auth_headers):
    other = User(username="other", password_hash=generate_password_hash("x" * 12))
    db.session.add(other)
    db.session.flush()
    their_account = _make_account(other.id)
    their_txn = _make_transaction(their_account.id, CURRENT_MONTH, "-5.00", "Theirs")

    response = client.delete(f"/api/transactions/{their_txn.id}", headers=auth_headers)
    assert response.status_code == 403
    assert db.session.get(Transaction, their_txn.id) is not None


def test_delete_transaction_without_token_returns_401(client, test_user, auth_headers):
    account = _make_account(test_user.id)
    txn = _make_transaction(account.id, CURRENT_MONTH, "-5.00", "X")
    assert client.delete(f"/api/transactions/{txn.id}").status_code == 401


# ---------------------------------------------------------------------------
# auto-categorization by prior choice (changes/013)
# ---------------------------------------------------------------------------


def test_manual_transaction_auto_categorizes_from_prior_same_merchant(client, test_user, auth_headers):
    account = _make_account(test_user.id)
    category = _make_category(test_user.id, name="Coffee")
    _make_transaction(account.id, CURRENT_MONTH, "-4.00", "BLUE BOTTLE", category_id=category.id)

    response = client.post(
        "/api/transactions",
        json={"account_id": account.id, "posted_at": CURRENT_MONTH.isoformat(), "amount": "-4.50", "description": "BLUE BOTTLE"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["category_id"] == category.id
    assert body["category_name"] == "Coffee"


def test_manual_transaction_no_prior_match_stays_uncategorized(client, test_user, auth_headers):
    account = _make_account(test_user.id)
    _make_category(test_user.id, name="Coffee")

    response = client.post(
        "/api/transactions",
        json={"account_id": account.id, "posted_at": CURRENT_MONTH.isoformat(), "amount": "-4.50", "description": "UNKNOWN CAFE"},
        headers=auth_headers,
    )
    assert response.get_json()["category_id"] is None


def test_manual_transaction_explicit_category_wins_over_inference(client, test_user, auth_headers):
    account = _make_account(test_user.id)
    coffee = _make_category(test_user.id, name="Coffee")
    dining = _make_category(test_user.id, name="Dining")
    _make_transaction(account.id, CURRENT_MONTH, "-4.00", "BLUE BOTTLE", category_id=coffee.id)

    response = client.post(
        "/api/transactions",
        json={
            "account_id": account.id,
            "posted_at": CURRENT_MONTH.isoformat(),
            "amount": "-4.50",
            "description": "BLUE BOTTLE",
            "category_id": dining.id,
        },
        headers=auth_headers,
    )
    assert response.get_json()["category_id"] == dining.id
