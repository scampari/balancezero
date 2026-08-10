"""Integration tests for spec/budget-api.md — categories, allocations, budget view.

Every test here traces to a case in spec/budget-api.md's integration test contract.
Do not add cases here that aren't in the spec — extend the spec first.
"""

from datetime import date

from conftest import TEST_PASSWORD, TEST_USERNAME
from models import BudgetAllocation, Category, db
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
