"""Integration tests for spec/budget-api.md — categories, allocations, budget view.

Every test here traces to a case in spec/budget-api.md's integration test contract.
Do not add cases here that aren't in the spec — extend the spec first.
"""

from datetime import date

from conftest import TEST_PASSWORD, TEST_USERNAME
from models import BudgetAllocation, Category, User, db
from werkzeug.security import generate_password_hash

CURRENT_MONTH = date.today().replace(day=1).isoformat()


def _create_category(client, auth_headers, name="Groceries"):
    return client.post("/api/categories", json={"name": name}, headers=auth_headers)


# ---------------------------------------------------------------------------
# POST /api/categories
# ---------------------------------------------------------------------------


def test_create_category_with_valid_name_returns_201(client, test_user, auth_headers):
    # Act
    response = _create_category(client, auth_headers, name="Groceries")

    # Assert
    assert response.status_code == 201
    body = response.get_json()
    assert body["name"] == "Groceries"
    assert isinstance(body["id"], int)

    # Assert side effect
    category = db.session.get(Category, body["id"])
    assert category is not None
    assert category.user_id == test_user.id


def test_create_category_without_token_returns_401(client, test_user):
    # Act
    response = client.post("/api/categories", json={"name": "Groceries"})

    # Assert
    assert response.status_code == 401


def test_create_category_with_empty_name_returns_400(client, test_user, auth_headers):
    # Act
    response = _create_category(client, auth_headers, name="")

    # Assert
    assert response.status_code == 400


def test_create_category_with_missing_name_returns_400(client, test_user, auth_headers):
    # Act
    response = client.post("/api/categories", json={}, headers=auth_headers)

    # Assert
    assert response.status_code == 400


def test_create_category_with_duplicate_name_returns_409(client, test_user, auth_headers):
    # Arrange
    _create_category(client, auth_headers, name="Groceries")

    # Act
    response = _create_category(client, auth_headers, name="Groceries")

    # Assert
    assert response.status_code == 409
    assert Category.query.filter_by(user_id=test_user.id, name="Groceries").count() == 1


def test_create_subcategory_with_valid_parent_returns_201(client, test_user, auth_headers):
    # Arrange
    parent_id = _create_category(client, auth_headers, name="Food").get_json()["id"]

    # Act
    response = client.post(
        "/api/categories", json={"name": "Restaurants", "parent_id": parent_id}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 201
    body = response.get_json()
    assert body["parent_id"] == parent_id

    # Assert side effect
    category = db.session.get(Category, body["id"])
    assert category.parent_id == parent_id


def test_create_category_without_parent_returns_null_parent_id(client, test_user, auth_headers):
    # Act
    response = _create_category(client, auth_headers, name="Food")

    # Assert
    assert response.get_json()["parent_id"] is None


def test_create_subcategory_with_nonexistent_parent_returns_404(client, test_user, auth_headers):
    # Act
    response = client.post(
        "/api/categories", json={"name": "Restaurants", "parent_id": 999999}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 404


def test_create_subcategory_with_another_users_parent_returns_403(client, test_user, auth_headers):
    # Arrange
    other_user = User(username="cat-other", password_hash=generate_password_hash("irrelevant"))
    db.session.add(other_user)
    db.session.commit()
    other_category = Category(user_id=other_user.id, name="NotYours")
    db.session.add(other_category)
    db.session.commit()

    # Act
    response = client.post(
        "/api/categories", json={"name": "Restaurants", "parent_id": other_category.id}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 403


def test_create_subcategory_of_a_subcategory_returns_400(client, test_user, auth_headers):
    # Arrange — two levels already: Food -> Restaurants
    parent_id = _create_category(client, auth_headers, name="Food").get_json()["id"]
    subcategory_id = client.post(
        "/api/categories", json={"name": "Restaurants", "parent_id": parent_id}, headers=auth_headers
    ).get_json()["id"]

    # Act — try a third level under Restaurants
    response = client.post(
        "/api/categories", json={"name": "Fast Food", "parent_id": subcategory_id}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/categories/<id>/allocations
# ---------------------------------------------------------------------------


def test_set_allocation_creates_new_allocation_returns_200(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers).get_json()["id"]

    # Act
    response = client.post(
        f"/api/categories/{category_id}/allocations",
        json={"month": CURRENT_MONTH, "amount": "150.00"},
        headers=auth_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body["category_id"] == category_id
    assert body["month"] == CURRENT_MONTH

    # Assert side effect
    allocation = BudgetAllocation.query.filter_by(category_id=category_id, month=date.fromisoformat(CURRENT_MONTH)).first()
    assert allocation is not None
    assert str(allocation.allocated_amount) == "150.00"


def test_set_allocation_on_existing_month_updates_it_not_duplicates(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers).get_json()["id"]
    client.post(
        f"/api/categories/{category_id}/allocations",
        json={"month": CURRENT_MONTH, "amount": "100.00"},
        headers=auth_headers,
    )

    # Act — second allocation for the same category+month
    response = client.post(
        f"/api/categories/{category_id}/allocations",
        json={"month": CURRENT_MONTH, "amount": "200.00"},
        headers=auth_headers,
    )

    # Assert
    assert response.status_code == 200
    assert response.get_json()["allocated_amount"] == "200.00"
    matching = BudgetAllocation.query.filter_by(
        category_id=category_id, month=date.fromisoformat(CURRENT_MONTH)
    ).all()
    assert len(matching) == 1
    assert str(matching[0].allocated_amount) == "200.00"


def test_set_allocation_without_token_returns_401(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers).get_json()["id"]

    # Act
    response = client.post(
        f"/api/categories/{category_id}/allocations",
        json={"month": CURRENT_MONTH, "amount": "50.00"},
    )

    # Assert
    assert response.status_code == 401


def test_set_allocation_on_nonexistent_category_returns_404(client, test_user, auth_headers):
    # Act
    response = client.post(
        "/api/categories/999999/allocations",
        json={"month": CURRENT_MONTH, "amount": "50.00"},
        headers=auth_headers,
    )

    # Assert
    assert response.status_code == 404


def test_set_allocation_on_another_users_category_returns_403(client, test_user, auth_headers):
    # Arrange — a second user owns a category
    other_user = type(test_user)(username="other", password_hash=generate_password_hash("irrelevant"))
    db.session.add(other_user)
    db.session.commit()
    other_category = Category(user_id=other_user.id, name="NotYours")
    db.session.add(other_category)
    db.session.commit()

    # Act — test_user's token, other user's category
    response = client.post(
        f"/api/categories/{other_category.id}/allocations",
        json={"month": CURRENT_MONTH, "amount": "50.00"},
        headers=auth_headers,
    )

    # Assert
    assert response.status_code == 403


def test_set_allocation_missing_month_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers).get_json()["id"]

    # Act
    response = client.post(
        f"/api/categories/{category_id}/allocations", json={"amount": "50.00"}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 400


def test_set_allocation_missing_amount_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers).get_json()["id"]

    # Act
    response = client.post(
        f"/api/categories/{category_id}/allocations", json={"month": CURRENT_MONTH}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 400


def test_set_allocation_invalid_amount_format_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers).get_json()["id"]

    # Act
    response = client.post(
        f"/api/categories/{category_id}/allocations",
        json={"month": CURRENT_MONTH, "amount": "not-a-number"},
        headers=auth_headers,
    )

    # Assert
    assert response.status_code == 400


def test_set_allocation_negative_amount_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers).get_json()["id"]

    # Act
    response = client.post(
        f"/api/categories/{category_id}/allocations",
        json={"month": CURRENT_MONTH, "amount": "-10.00"},
        headers=auth_headers,
    )

    # Assert
    assert response.status_code == 400


def test_set_allocation_invalid_month_format_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers).get_json()["id"]

    # Act
    response = client.post(
        f"/api/categories/{category_id}/allocations",
        json={"month": "not-a-date", "amount": "50.00"},
        headers=auth_headers,
    )

    # Assert
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/budget
# ---------------------------------------------------------------------------


def test_get_budget_returns_ready_to_assign_and_categories(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]
    client.post(
        f"/api/categories/{category_id}/allocations",
        json={"month": CURRENT_MONTH, "amount": "150.00"},
        headers=auth_headers,
    )

    # Act
    response = client.get(f"/api/budget?month={CURRENT_MONTH}", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body["month"] == CURRENT_MONTH
    assert "ready_to_assign" in body
    assert any(c["id"] == category_id and c["name"] == "Groceries" for c in body["categories"])
    matching_category = next(c for c in body["categories"] if c["id"] == category_id)
    assert matching_category["allocated_this_month"] == "150.00"


def test_get_budget_without_month_param_defaults_to_current_month(client, test_user, auth_headers):
    # Act
    response = client.get("/api/budget", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert response.get_json()["month"] == CURRENT_MONTH


def test_get_budget_without_token_returns_401(client, test_user):
    # Act
    response = client.get("/api/budget")

    # Assert
    assert response.status_code == 401


def test_get_budget_invalid_month_format_returns_400(client, test_user, auth_headers):
    # Act
    response = client.get("/api/budget?month=not-a-date", headers=auth_headers)

    # Assert
    assert response.status_code == 400


def test_get_budget_only_shows_authenticated_users_categories(client, test_user, auth_headers):
    # Arrange — a second user has their own category
    other_user = type(test_user)(username="other2", password_hash=generate_password_hash("irrelevant"))
    db.session.add(other_user)
    db.session.commit()
    db.session.add(Category(user_id=other_user.id, name="NotYours"))
    db.session.commit()

    # Act
    response = client.get("/api/budget", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    names = [c["name"] for c in response.get_json()["categories"]]
    assert "NotYours" not in names


# ---------------------------------------------------------------------------
# POST/GET /api/categories/<id>/target
# ---------------------------------------------------------------------------


def _set_target(client, auth_headers, category_id, target_type, target_amount, target_date=None):
    payload = {"target_type": target_type, "target_amount": target_amount}
    if target_date is not None:
        payload["target_date"] = target_date
    return client.post(f"/api/categories/{category_id}/target", json=payload, headers=auth_headers)


def _months_remaining_through_year_end(today):
    return 12 - today.month + 1


def _months_remaining_through(today, target_date):
    return (target_date.year - today.year) * 12 + (target_date.month - today.month) + 1


def test_set_monthly_target_returns_201(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = _set_target(client, auth_headers, category_id, "monthly", "50.00")

    # Assert
    assert response.status_code == 201
    body = response.get_json()
    assert body["category_id"] == category_id
    assert body["target_type"] == "monthly"
    assert body["target_amount"] == "50.00"
    assert body["target_date"] is None
    assert body["monthly_target_amount"] == "50.00"

    # Assert side effect
    from models import CategoryTarget

    target = CategoryTarget.query.filter_by(category_id=category_id, superseded_at=None).first()
    assert target is not None
    assert str(target.target_amount) == "50.00"


def test_set_yearly_target_computes_monthly_target_amount(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Vacation").get_json()["id"]
    months = _months_remaining_through_year_end(date.today())
    total = f"{months * 100}.00"
    expected_monthly = "100.00"

    # Act
    response = _set_target(client, auth_headers, category_id, "yearly", total)

    # Assert
    assert response.status_code == 201
    body = response.get_json()
    assert body["target_type"] == "yearly"
    assert body["target_amount"] == total
    assert body["target_date"] is None
    assert body["monthly_target_amount"] == expected_monthly


def test_set_custom_target_computes_monthly_target_amount(client, test_user, auth_headers):
    # Arrange — a custom target exactly one year (13 inclusive months) out
    category_id = _create_category(client, auth_headers, name="New Car").get_json()["id"]
    today = date.today()
    target_date = date(today.year + 1, today.month, 1)
    months = _months_remaining_through(today, target_date)
    total = f"{months * 100}.00"
    expected_monthly = "100.00"

    # Act
    response = _set_target(client, auth_headers, category_id, "custom", total, target_date.isoformat())

    # Assert
    assert response.status_code == 201
    body = response.get_json()
    assert body["target_type"] == "custom"
    assert body["target_date"] == target_date.isoformat()
    assert body["monthly_target_amount"] == expected_monthly


def test_set_target_supersedes_previous_target_not_deletes(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]
    first = _set_target(client, auth_headers, category_id, "monthly", "50.00").get_json()

    # Act
    second = _set_target(client, auth_headers, category_id, "monthly", "75.00").get_json()

    # Assert
    assert second["target_amount"] == "75.00"

    from models import CategoryTarget

    first_row = db.session.get(CategoryTarget, first["id"])
    assert first_row is not None  # not deleted
    assert first_row.superseded_at is not None  # but superseded

    active = CategoryTarget.query.filter_by(category_id=category_id, superseded_at=None).all()
    assert len(active) == 1
    assert active[0].id == second["id"]


def test_set_target_without_token_returns_401(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = client.post(f"/api/categories/{category_id}/target", json={"target_type": "monthly", "target_amount": "50.00"})

    # Assert
    assert response.status_code == 401


def test_set_target_on_nonexistent_category_returns_404(client, test_user, auth_headers):
    # Act
    response = _set_target(client, auth_headers, 999999, "monthly", "50.00")

    # Assert
    assert response.status_code == 404


def test_set_target_on_another_users_category_returns_403(client, test_user, auth_headers):
    # Arrange
    other_user = type(test_user)(username="target-other", password_hash=generate_password_hash("irrelevant"))
    db.session.add(other_user)
    db.session.commit()
    other_category = Category(user_id=other_user.id, name="NotYours")
    db.session.add(other_category)
    db.session.commit()

    # Act
    response = _set_target(client, auth_headers, other_category.id, "monthly", "50.00")

    # Assert
    assert response.status_code == 403


def test_set_target_missing_target_type_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = client.post(f"/api/categories/{category_id}/target", json={"target_amount": "50.00"}, headers=auth_headers)

    # Assert
    assert response.status_code == 400


def test_set_target_invalid_target_type_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = _set_target(client, auth_headers, category_id, "weekly", "50.00")

    # Assert
    assert response.status_code == 400


def test_set_target_missing_target_amount_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = client.post(f"/api/categories/{category_id}/target", json={"target_type": "monthly"}, headers=auth_headers)

    # Assert
    assert response.status_code == 400


def test_set_target_invalid_target_amount_format_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = _set_target(client, auth_headers, category_id, "monthly", "not-a-number")

    # Assert
    assert response.status_code == 400


def test_set_target_zero_amount_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = _set_target(client, auth_headers, category_id, "monthly", "0.00")

    # Assert
    assert response.status_code == 400


def test_set_target_negative_amount_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = _set_target(client, auth_headers, category_id, "monthly", "-50.00")

    # Assert
    assert response.status_code == 400


def test_set_target_custom_missing_target_date_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = _set_target(client, auth_headers, category_id, "custom", "600.00")

    # Assert
    assert response.status_code == 400


def test_set_target_custom_invalid_target_date_format_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = _set_target(client, auth_headers, category_id, "custom", "600.00", "not-a-date")

    # Assert
    assert response.status_code == 400


def test_set_target_custom_target_date_not_in_future_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]
    current_month = date.today().replace(day=1).isoformat()

    # Act — target_date within the current month, not after it
    response = _set_target(client, auth_headers, category_id, "custom", "600.00", current_month)

    # Assert
    assert response.status_code == 400


def test_set_target_monthly_with_target_date_returns_400(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]
    future_date = date(date.today().year + 1, date.today().month, 1).isoformat()

    # Act — target_date is forbidden for monthly
    response = _set_target(client, auth_headers, category_id, "monthly", "50.00", future_date)

    # Assert
    assert response.status_code == 400


def test_get_target_returns_active_target(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]
    _set_target(client, auth_headers, category_id, "monthly", "50.00")

    # Act
    response = client.get(f"/api/categories/{category_id}/target", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body["target"]["target_type"] == "monthly"
    assert body["target"]["target_amount"] == "50.00"


def test_get_target_returns_null_when_none_set(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = client.get(f"/api/categories/{category_id}/target", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert response.get_json()["target"] is None


def test_get_target_without_token_returns_401(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = client.get(f"/api/categories/{category_id}/target")

    # Assert
    assert response.status_code == 401


def test_get_target_on_nonexistent_category_returns_404(client, test_user, auth_headers):
    # Act
    response = client.get("/api/categories/999999/target", headers=auth_headers)

    # Assert
    assert response.status_code == 404


def test_get_target_on_another_users_category_returns_403(client, test_user, auth_headers):
    # Arrange
    other_user = type(test_user)(username="target-other2", password_hash=generate_password_hash("irrelevant"))
    db.session.add(other_user)
    db.session.commit()
    other_category = Category(user_id=other_user.id, name="NotYours")
    db.session.add(other_category)
    db.session.commit()

    # Act
    response = client.get(f"/api/categories/{other_category.id}/target", headers=auth_headers)

    # Assert
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/budget — ready_to_assign now reads is_income (005)
# ---------------------------------------------------------------------------


def _make_account_with_income(user_id, is_income_amount, plain_uncategorized_amount=None):
    """Arrange helper — one account, one is_income transaction, optionally one
    plain uncategorized (non-income) transaction. Kept local (not a shared
    fixture) so this test file stays self-contained, matching the existing
    local-import style for CategoryTarget above."""
    from decimal import Decimal

    from models import Account, Transaction

    account = Account(user_id=user_id, name="Checking")
    db.session.add(account)
    db.session.commit()

    db.session.add(
        Transaction(
            account_id=account.id,
            category_id=None,
            posted_at=date.today().replace(day=1),
            amount=Decimal(is_income_amount),
            description="Paycheck",
            is_income=True,
        )
    )
    if plain_uncategorized_amount is not None:
        db.session.add(
            Transaction(
                account_id=account.id,
                category_id=None,
                posted_at=date.today().replace(day=1),
                amount=Decimal(plain_uncategorized_amount),
                description="Unreviewed inflow",
                is_income=False,
            )
        )
    db.session.commit()
    return account


def test_get_budget_ready_to_assign_counts_is_income_minus_allocations(client, test_user, auth_headers):
    # Arrange — 1000 marked is_income, 500 plain uncategorized inflow, 150 allocated.
    # New formula: SUM(is_income) - SUM(allocated) = 1000 - 150 = 850.
    # (Old "uncategorized inflow" formula would have given 1500 - 150 = 1350.)
    from decimal import Decimal

    _make_account_with_income(test_user.id, "1000.00", plain_uncategorized_amount="500.00")
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]
    client.post(
        f"/api/categories/{category_id}/allocations",
        json={"month": CURRENT_MONTH, "amount": "150.00"},
        headers=auth_headers,
    )

    # Act
    response = client.get(f"/api/budget?month={CURRENT_MONTH}", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert Decimal(response.get_json()["ready_to_assign"]) == Decimal("850.00")


def test_get_budget_ready_to_assign_excludes_plain_uncategorized_inflow(client, test_user, auth_headers):
    # Arrange — a single uncategorized inflow that is NOT marked is_income, no allocations.
    # New formula counts only is_income, so ready_to_assign is 0 (old formula gave 500).
    from decimal import Decimal

    from models import Account, Transaction

    account = Account(user_id=test_user.id, name="Checking")
    db.session.add(account)
    db.session.commit()
    db.session.add(
        Transaction(
            account_id=account.id,
            category_id=None,
            posted_at=date.today().replace(day=1),
            amount=Decimal("500.00"),
            description="Unreviewed inflow",
            is_income=False,
        )
    )
    db.session.commit()

    # Act
    response = client.get("/api/budget", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert Decimal(response.get_json()["ready_to_assign"]) == Decimal("0")


# ---------------------------------------------------------------------------
# GET /api/budget — per-category shape gains target (005)
# ---------------------------------------------------------------------------


def test_get_budget_category_without_target_has_null_target(client, test_user, auth_headers):
    # Arrange
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]

    # Act
    response = client.get(f"/api/budget?month={CURRENT_MONTH}", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    entry = next(c for c in response.get_json()["categories"] if c["id"] == category_id)
    assert "target" in entry
    assert entry["target"] is None


def test_get_budget_category_with_active_target_includes_target_shape(client, test_user, auth_headers):
    # Arrange — a monthly target on the category
    category_id = _create_category(client, auth_headers, name="Groceries").get_json()["id"]
    _set_target(client, auth_headers, category_id, "monthly", "200.00")

    # Act
    response = client.get(f"/api/budget?month={CURRENT_MONTH}", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    entry = next(c for c in response.get_json()["categories"] if c["id"] == category_id)
    assert "target" in entry
    assert entry["target"] is not None
    assert entry["target"]["target_type"] == "monthly"
    assert entry["target"]["target_amount"] == "200.00"
    assert entry["target"]["target_date"] is None
    assert entry["target"]["monthly_target_amount"] == "200.00"


# ---------------------------------------------------------------------------
# PATCH /api/categories/<id> — rename / reparent / archive / reorder (006)
# ---------------------------------------------------------------------------


def _new_category(client, auth_headers, name, parent_id=None):
    payload = {"name": name}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    return client.post("/api/categories", json=payload, headers=auth_headers).get_json()


def _patch_category(client, auth_headers, category_id, **patch):
    return client.patch(f"/api/categories/{category_id}", json=patch, headers=auth_headers)


def test_patch_category_renames(client, test_user, auth_headers):
    # Arrange
    cid = _new_category(client, auth_headers, "Groceris")["id"]

    # Act
    response = _patch_category(client, auth_headers, cid, name="Groceries")

    # Assert
    assert response.status_code == 200
    assert response.get_json()["name"] == "Groceries"
    assert db.session.get(Category, cid).name == "Groceries"


def test_patch_category_rename_to_duplicate_returns_409(client, test_user, auth_headers):
    # Arrange
    _new_category(client, auth_headers, "Rent")
    cid = _new_category(client, auth_headers, "Groceries")["id"]

    # Act
    response = _patch_category(client, auth_headers, cid, name="Rent")

    # Assert
    assert response.status_code == 409
    assert db.session.get(Category, cid).name == "Groceries"


def test_patch_category_rename_to_empty_returns_400(client, test_user, auth_headers):
    # Arrange
    cid = _new_category(client, auth_headers, "Groceries")["id"]

    # Act
    response = _patch_category(client, auth_headers, cid, name="   ")

    # Assert
    assert response.status_code == 400


def test_patch_category_reparents_under_top_level(client, test_user, auth_headers):
    # Arrange
    parent = _new_category(client, auth_headers, "Food")["id"]
    cid = _new_category(client, auth_headers, "Groceries")["id"]

    # Act
    response = _patch_category(client, auth_headers, cid, parent_id=parent)

    # Assert
    assert response.status_code == 200
    assert response.get_json()["parent_id"] == parent
    assert db.session.get(Category, cid).parent_id == parent


def test_patch_category_reparent_to_null_promotes_to_top_level(client, test_user, auth_headers):
    # Arrange
    parent = _new_category(client, auth_headers, "Food")["id"]
    cid = _new_category(client, auth_headers, "Groceries", parent_id=parent)["id"]

    # Act
    response = _patch_category(client, auth_headers, cid, parent_id=None)

    # Assert
    assert response.status_code == 200
    assert response.get_json()["parent_id"] is None
    assert db.session.get(Category, cid).parent_id is None


def test_patch_category_reparent_to_self_returns_400(client, test_user, auth_headers):
    # Arrange
    cid = _new_category(client, auth_headers, "Groceries")["id"]

    # Act
    response = _patch_category(client, auth_headers, cid, parent_id=cid)

    # Assert
    assert response.status_code == 400


def test_patch_category_reparent_under_a_subcategory_returns_400(client, test_user, auth_headers):
    # Arrange — two levels only
    parent = _new_category(client, auth_headers, "Food")["id"]
    sub = _new_category(client, auth_headers, "Groceries", parent_id=parent)["id"]
    cid = _new_category(client, auth_headers, "Dining")["id"]

    # Act
    response = _patch_category(client, auth_headers, cid, parent_id=sub)

    # Assert
    assert response.status_code == 400


def test_patch_category_reparent_a_category_that_has_children_returns_400(client, test_user, auth_headers):
    # Arrange
    other_top = _new_category(client, auth_headers, "Fixed")["id"]
    parent = _new_category(client, auth_headers, "Food")["id"]
    _new_category(client, auth_headers, "Groceries", parent_id=parent)

    # Act — "Food" already has a child, cannot itself become a subcategory
    response = _patch_category(client, auth_headers, parent, parent_id=other_top)

    # Assert
    assert response.status_code == 400


def test_patch_category_reparent_to_another_users_category_returns_403(client, test_user, auth_headers):
    # Arrange
    other_user = User(username="cat-other", password_hash=generate_password_hash("irrelevant"))
    db.session.add(other_user)
    db.session.commit()
    other_parent = Category(user_id=other_user.id, name="TheirFood")
    db.session.add(other_parent)
    db.session.commit()
    cid = _new_category(client, auth_headers, "Groceries")["id"]

    # Act
    response = _patch_category(client, auth_headers, cid, parent_id=other_parent.id)

    # Assert
    assert response.status_code == 403


def test_patch_category_archives(client, test_user, auth_headers):
    # Arrange
    cid = _new_category(client, auth_headers, "Old Category")["id"]

    # Act
    response = _patch_category(client, auth_headers, cid, archived=True)

    # Assert
    assert response.status_code == 200
    assert response.get_json()["archived"] is True
    assert db.session.get(Category, cid).archived is True


def test_patch_category_archive_parent_with_active_child_returns_400(client, test_user, auth_headers):
    # Arrange
    parent = _new_category(client, auth_headers, "Food")["id"]
    _new_category(client, auth_headers, "Groceries", parent_id=parent)

    # Act
    response = _patch_category(client, auth_headers, parent, archived=True)

    # Assert
    assert response.status_code == 400
    assert db.session.get(Category, parent).archived is False


def test_patch_category_unarchives(client, test_user, auth_headers):
    # Arrange
    cid = _new_category(client, auth_headers, "Old Category")["id"]
    _patch_category(client, auth_headers, cid, archived=True)

    # Act
    response = _patch_category(client, auth_headers, cid, archived=False)

    # Assert
    assert response.status_code == 200
    assert response.get_json()["archived"] is False
    assert db.session.get(Category, cid).archived is False


def test_patch_category_unarchive_child_while_parent_archived_returns_400(client, test_user, auth_headers):
    # Arrange — archive the child first, then the parent
    parent = _new_category(client, auth_headers, "Food")["id"]
    child = _new_category(client, auth_headers, "Groceries", parent_id=parent)["id"]
    _patch_category(client, auth_headers, child, archived=True)
    _patch_category(client, auth_headers, parent, archived=True)

    # Act
    response = _patch_category(client, auth_headers, child, archived=False)

    # Assert
    assert response.status_code == 400
    assert db.session.get(Category, child).archived is True


def test_patch_category_archived_absent_from_categories_present_in_archived_list(client, test_user, auth_headers):
    # Arrange
    keep = _new_category(client, auth_headers, "Groceries")["id"]
    gone = _new_category(client, auth_headers, "Defunct")["id"]
    _patch_category(client, auth_headers, gone, archived=True)

    # Act
    body = client.get(f"/api/budget?month={CURRENT_MONTH}", headers=auth_headers).get_json()

    # Assert
    active_ids = {c["id"] for c in body["categories"]}
    archived_ids = {c["id"] for c in body["archived_categories"]}
    assert keep in active_ids
    assert gone not in active_ids
    assert gone in archived_ids


def test_patch_category_position_reorders_siblings(client, test_user, auth_headers):
    # Arrange — three top-level categories in creation order
    a = _new_category(client, auth_headers, "Alpha")["id"]
    b = _new_category(client, auth_headers, "Bravo")["id"]
    c = _new_category(client, auth_headers, "Charlie")["id"]

    # Act — move Charlie to the front
    response = _patch_category(client, auth_headers, c, position=0)

    # Assert
    assert response.status_code == 200
    order = [cat["id"] for cat in client.get(f"/api/budget?month={CURRENT_MONTH}", headers=auth_headers).get_json()["categories"]]
    assert order == [c, a, b]
    # positions packed gap-free
    positions = sorted(db.session.get(Category, x).position for x in (a, b, c))
    assert positions == [0, 1, 2]


def test_patch_category_no_recognized_fields_returns_400(client, test_user, auth_headers):
    # Arrange
    cid = _new_category(client, auth_headers, "Groceries")["id"]

    # Act
    response = client.patch(f"/api/categories/{cid}", json={"color": "blue"}, headers=auth_headers)

    # Assert
    assert response.status_code == 400


def test_patch_category_without_token_returns_401(client, test_user, auth_headers):
    # Arrange
    cid = _new_category(client, auth_headers, "Groceries")["id"]

    # Act
    response = client.patch(f"/api/categories/{cid}", json={"name": "X"})

    # Assert
    assert response.status_code == 401


def test_patch_category_nonexistent_returns_404(client, test_user, auth_headers):
    # Act
    response = _patch_category(client, auth_headers, 999999, name="X")

    # Assert
    assert response.status_code == 404


def test_patch_category_another_users_category_returns_403(client, test_user, auth_headers):
    # Arrange
    other_user = User(username="cat-other2", password_hash=generate_password_hash("irrelevant"))
    db.session.add(other_user)
    db.session.commit()
    theirs = Category(user_id=other_user.id, name="Theirs")
    db.session.add(theirs)
    db.session.commit()

    # Act
    response = _patch_category(client, auth_headers, theirs.id, name="Mine")

    # Assert
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/budget — spent_this_month, totals, target progress (006)
# ---------------------------------------------------------------------------


def _account(user_id, name="Checking"):
    from models import Account

    account = Account(user_id=user_id, name=name)
    db.session.add(account)
    db.session.commit()
    return account


def _txn(account_id, posted_at, amount, category_id=None, description="txn"):
    from decimal import Decimal

    from models import Transaction

    db.session.add(
        Transaction(
            account_id=account_id,
            category_id=category_id,
            posted_at=posted_at,
            amount=Decimal(amount),
            description=description,
        )
    )
    db.session.commit()


def _prev_month_date():
    today = date.today().replace(day=1)
    return date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)


def _budget_entry(client, auth_headers, category_id, month=CURRENT_MONTH):
    body = client.get(f"/api/budget?month={month}", headers=auth_headers).get_json()
    return next(c for c in body["categories"] if c["id"] == category_id)


def test_get_budget_spent_this_month_sums_only_the_viewed_month(client, test_user, auth_headers):
    # Arrange
    from decimal import Decimal

    cid = _new_category(client, auth_headers, "Groceries")["id"]
    account = _account(test_user.id)
    _txn(account.id, date.today().replace(day=1), "-40.00", category_id=cid)
    _txn(account.id, date.today().replace(day=1), "-10.00", category_id=cid)
    _txn(account.id, _prev_month_date(), "-99.00", category_id=cid)

    # Act / Assert
    entry = _budget_entry(client, auth_headers, cid)
    assert Decimal(entry["spent_this_month"]) == Decimal("-50.00")


def test_get_budget_spent_this_month_is_zero_without_transactions(client, test_user, auth_headers):
    # Arrange
    from decimal import Decimal

    cid = _new_category(client, auth_headers, "Groceries")["id"]

    # Act / Assert
    entry = _budget_entry(client, auth_headers, cid)
    assert Decimal(entry["spent_this_month"]) == Decimal("0")


def test_get_budget_totals_sum_active_categories_and_exclude_archived(client, test_user, auth_headers):
    # Arrange
    from decimal import Decimal

    keep = _new_category(client, auth_headers, "Groceries")["id"]
    gone = _new_category(client, auth_headers, "Defunct")["id"]
    account = _account(test_user.id)
    _txn(account.id, date.today().replace(day=1), "-30.00", category_id=keep)
    _txn(account.id, date.today().replace(day=1), "-500.00", category_id=gone)
    client.post(f"/api/categories/{keep}/allocations", json={"month": CURRENT_MONTH, "amount": "100.00"}, headers=auth_headers)
    client.post(f"/api/categories/{gone}/allocations", json={"month": CURRENT_MONTH, "amount": "999.00"}, headers=auth_headers)
    _patch_category(client, auth_headers, gone, archived=True)

    # Act
    body = client.get(f"/api/budget?month={CURRENT_MONTH}", headers=auth_headers).get_json()

    # Assert — only "Groceries" counts
    assert Decimal(body["totals"]["budgeted"]) == Decimal("100.00")
    assert Decimal(body["totals"]["spent"]) == Decimal("-30.00")
    assert Decimal(body["totals"]["available"]) == Decimal("70.00")


def test_get_budget_yearly_target_needed_this_month_accounts_for_funded(client, test_user, auth_headers):
    # Arrange — yearly $1200 target, envelope already holds $200 (allocated).
    from decimal import Decimal

    cid = _new_category(client, auth_headers, "Car Repair")["id"]
    _set_target(client, auth_headers, cid, "yearly", "1200.00")
    client.post(f"/api/categories/{cid}/allocations", json={"month": CURRENT_MONTH, "amount": "200.00"}, headers=auth_headers)
    months = _months_remaining_through_year_end(date.today())

    # Act
    entry = _budget_entry(client, auth_headers, cid)

    # Assert
    assert entry["target"]["months_remaining"] == months
    assert Decimal(entry["target"]["funded"]) == Decimal("200.00")
    expected = (Decimal("1200.00") - Decimal("200.00")) / months
    assert Decimal(entry["target"]["needed_this_month"]) == expected.quantize(Decimal("0.01"))


def test_get_budget_target_needed_this_month_is_zero_when_fully_funded(client, test_user, auth_headers):
    # Arrange
    from decimal import Decimal

    cid = _new_category(client, auth_headers, "Vacation")["id"]
    _set_target(client, auth_headers, cid, "yearly", "300.00")
    client.post(f"/api/categories/{cid}/allocations", json={"month": CURRENT_MONTH, "amount": "500.00"}, headers=auth_headers)

    # Act
    entry = _budget_entry(client, auth_headers, cid)

    # Assert
    assert Decimal(entry["target"]["needed_this_month"]) == Decimal("0")
    assert Decimal(entry["target"]["progress"]) == Decimal("1")


def test_get_budget_monthly_target_months_remaining_is_one(client, test_user, auth_headers):
    # Arrange
    cid = _new_category(client, auth_headers, "Groceries")["id"]
    _set_target(client, auth_headers, cid, "monthly", "400.00")

    # Act
    entry = _budget_entry(client, auth_headers, cid)

    # Assert
    assert entry["target"]["months_remaining"] == 1
    assert entry["target"]["needed_this_month"] == "400.00"


# ---------------------------------------------------------------------------
# Category groups — a top-level category with children (changes/014)
# ---------------------------------------------------------------------------


def _allocate(client, auth_headers, category_id, amount, month=CURRENT_MONTH):
    return client.post(
        f"/api/categories/{category_id}/allocations",
        json={"month": month, "amount": amount},
        headers=auth_headers,
    )


def _add_txn(user_id, category_id, amount, description="X"):
    from models import Account, Transaction

    account = Account.query.filter_by(user_id=user_id).first()
    if account is None:
        account = Account(user_id=user_id, name="Checking")
        db.session.add(account)
        db.session.flush()
    db.session.add(Transaction(
        account_id=account.id, category_id=category_id,
        posted_at=date.today(), amount=amount, description=description,
    ))
    db.session.commit()


def test_top_level_with_children_is_a_group_summing_its_children(client, test_user, auth_headers):
    food = _create_category(client, auth_headers, name="Food").get_json()["id"]
    groceries = client.post("/api/categories", json={"name": "Groceries", "parent_id": food}, headers=auth_headers).get_json()["id"]
    dining = client.post("/api/categories", json={"name": "Dining", "parent_id": food}, headers=auth_headers).get_json()["id"]
    _allocate(client, auth_headers, groceries, "100.00")
    _allocate(client, auth_headers, dining, "40.00")
    _add_txn(test_user.id, groceries, "-30.00")

    food_entry = _budget_entry(client, auth_headers, food)
    assert food_entry["is_group"] is True
    assert food_entry["allocated_this_month"] == "140.00"
    assert food_entry["spent_this_month"] == "-30.00"
    assert food_entry["available"] == "110.00"  # 140 allocated - 30 spent

    groceries_entry = _budget_entry(client, auth_headers, groceries)
    assert groceries_entry["is_group"] is False


def test_group_total_folds_in_the_parents_own_legacy_amounts(client, test_user, auth_headers):
    food = _create_category(client, auth_headers, name="Food").get_json()["id"]
    _allocate(client, auth_headers, food, "50.00")  # allowed — no children yet
    _add_txn(test_user.id, food, "-20.00")
    groceries = client.post("/api/categories", json={"name": "Groceries", "parent_id": food}, headers=auth_headers).get_json()["id"]
    _allocate(client, auth_headers, groceries, "100.00")

    food_entry = _budget_entry(client, auth_headers, food)
    assert food_entry["allocated_this_month"] == "150.00"  # 50 own + 100 child
    assert food_entry["spent_this_month"] == "-20.00"
    assert food_entry["available"] == "130.00"  # 150 - 20


def test_group_is_not_double_counted_in_budget_totals(client, test_user, auth_headers):
    food = _create_category(client, auth_headers, name="Food").get_json()["id"]
    groceries = client.post("/api/categories", json={"name": "Groceries", "parent_id": food}, headers=auth_headers).get_json()["id"]
    _allocate(client, auth_headers, groceries, "100.00")

    body = client.get("/api/budget", headers=auth_headers).get_json()
    assert body["totals"]["budgeted"] == "100.00"  # child once, not child + group


def test_top_level_without_children_is_not_a_group(client, test_user, auth_headers):
    rent = _create_category(client, auth_headers, name="Rent").get_json()["id"]
    _allocate(client, auth_headers, rent, "500.00")

    entry = _budget_entry(client, auth_headers, rent)
    assert entry["is_group"] is False
    assert entry["allocated_this_month"] == "500.00"


def test_archived_child_does_not_make_the_parent_a_group(client, test_user, auth_headers):
    food = _create_category(client, auth_headers, name="Food").get_json()["id"]
    sub = client.post("/api/categories", json={"name": "Sub", "parent_id": food}, headers=auth_headers).get_json()["id"]
    client.patch(f"/api/categories/{sub}", json={"archived": True}, headers=auth_headers)

    entry = _budget_entry(client, auth_headers, food)
    assert entry["is_group"] is False


def test_set_allocation_on_a_group_category_returns_400(client, test_user, auth_headers):
    food = _create_category(client, auth_headers, name="Food").get_json()["id"]
    client.post("/api/categories", json={"name": "Groceries", "parent_id": food}, headers=auth_headers)

    response = _allocate(client, auth_headers, food, "100.00")
    assert response.status_code == 400
