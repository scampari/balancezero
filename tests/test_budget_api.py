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
