"""Integration tests for spec/accounts-api.md — list connected bank accounts.

Every test here traces to a case in spec/accounts-api.md's integration
test contract. Do not add cases here that aren't in the spec — extend the
spec first.
"""

from datetime import date, datetime
from decimal import Decimal

from models import Account, BudgetAllocation, Category, User, db
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


# ---------------------------------------------------------------------------
# PATCH /api/accounts/<id> — debt-payoff flag + payment-category conversion
# (changes/029 — traces to spec/accounts-api.md § "PATCH
# /api/accounts/<int:account_id> (changes/029)")
# ---------------------------------------------------------------------------


CURRENT_MONTH = date.today().replace(day=1).isoformat()


def _patch_account(client, auth_headers, account_id, **body):
    return client.patch(f"/api/accounts/{account_id}", json=body, headers=auth_headers)


def _new_top_level_category(client, auth_headers, name):
    return client.post("/api/categories", json={"name": name}, headers=auth_headers).get_json()


def _credit_card_with_payment_category(user_id, card_name="Rewards Card", group=None):
    """Build a credit Account + its "Credit Card Payments" group + bound
    payment Category — the state _ensure_payment_category produces. Pass an
    existing `group` to place a second card's payment category under it."""
    account = Account(
        user_id=user_id, name=card_name, type="credit", subtype="credit card", balance=Decimal("0")
    )
    db.session.add(account)
    db.session.flush()
    if group is None:
        group = Category(user_id=user_id, name="Credit Card Payments", position=99)
        db.session.add(group)
        db.session.flush()
    child_pos = (
        db.session.query(db.func.coalesce(db.func.max(Category.position), -1))
        .filter(Category.user_id == user_id, Category.parent_id == group.id)
        .scalar()
    )
    payment_cat = Category(
        user_id=user_id,
        name=card_name,
        parent_id=group.id,
        position=child_pos + 1,
        payment_account_id=account.id,
    )
    db.session.add(payment_cat)
    db.session.commit()
    return account, payment_cat, group


def test_list_accounts_includes_debt_payoff_false_by_default(client, test_user, auth_headers):
    # Arrange
    _make_account(test_user.id, name="Rewards Card", type="credit", subtype="credit card")

    # Act
    body = client.get("/api/accounts", headers=auth_headers).get_json()

    # Assert
    assert body["accounts"][0]["debt_payoff"] is False


def test_patch_account_sets_debt_payoff_and_echoes_the_account(client, test_user, auth_headers):
    # Arrange
    card = _make_account(test_user.id, name="Rewards Card", type="credit", subtype="credit card")

    # Act
    response = _patch_account(client, auth_headers, card.id, debt_payoff=True)

    # Assert
    assert response.status_code == 200
    account = response.get_json()["account"]
    assert account["id"] == card.id
    assert account["debt_payoff"] is True
    assert account["name"] == "Rewards Card"  # same shape as a GET list entry
    # Persisted — the list reflects it too.
    listed = client.get("/api/accounts", headers=auth_headers).get_json()["accounts"][0]
    assert listed["debt_payoff"] is True


def test_patch_account_debt_payoff_converts_a_bound_payment_category(
    client, test_user, auth_headers, credit_account
):
    # Arrange — a card whose payment category already carries an allocation,
    # plus two ordinary top-level categories.
    card, payment_cat, _group = credit_account
    _new_top_level_category(client, auth_headers, "Groceries")
    _new_top_level_category(client, auth_headers, "Rent")
    db.session.add(
        BudgetAllocation(
            user_id=test_user.id,
            category_id=payment_cat.id,
            month=date.fromisoformat(CURRENT_MONTH),
            allocated_amount=Decimal("125.00"),
        )
    )
    db.session.commit()
    payment_cat_id, payment_cat_name = payment_cat.id, payment_cat.name

    # Act
    response = _patch_account(client, auth_headers, card.id, debt_payoff=True)

    # Assert
    assert response.status_code == 200
    converted = db.session.get(Category, payment_cat_id)
    assert converted.payment_account_id is None
    assert converted.parent_id is None
    assert converted.name == payment_cat_name  # name untouched
    # The allocation survives verbatim.
    alloc = BudgetAllocation.query.filter_by(category_id=payment_cat_id).one()
    assert alloc.allocated_amount == Decimal("125.00")
    # It lands LAST among active top-level categories, positions gap-free.
    budget = client.get(f"/api/budget?month={CURRENT_MONTH}", headers=auth_headers).get_json()
    top_level = [c for c in budget["categories"] if c["parent_id"] is None]
    positions = sorted(c["position"] for c in top_level)
    assert positions == list(range(len(top_level)))  # 0..n-1, no gaps
    assert top_level[-1]["id"] == payment_cat_id
    assert top_level[-1]["position"] == len(top_level) - 1


def test_patch_account_debt_payoff_archives_an_emptied_payments_group(
    client, test_user, auth_headers, credit_account
):
    # Arrange — the fixture's group has exactly this one card under it.
    card, _payment_cat, group = credit_account

    # Act
    _patch_account(client, auth_headers, card.id, debt_payoff=True)

    # Assert
    assert db.session.get(Category, group.id).archived is True
    budget = client.get("/api/budget", headers=auth_headers).get_json()
    assert group.id not in {c["id"] for c in budget["categories"]}
    assert group.id in {c["id"] for c in budget["archived_categories"]}


def test_patch_account_debt_payoff_keeps_a_shared_payments_group_active(
    client, test_user, auth_headers
):
    # Arrange — two credit cards sharing one "Credit Card Payments" group.
    card_a, _pay_a, group = _credit_card_with_payment_category(test_user.id, "Card A")
    card_b, pay_b, _group = _credit_card_with_payment_category(test_user.id, "Card B", group=group)

    # Act — convert only card A.
    _patch_account(client, auth_headers, card_a.id, debt_payoff=True)

    # Assert — the group still has card B's payment category, so it stays.
    assert db.session.get(Category, group.id).archived is False
    assert db.session.get(Category, pay_b.id).parent_id == group.id


def test_patch_account_debt_payoff_with_no_payment_category_only_sets_the_flag(
    client, test_user, auth_headers
):
    # Arrange — a bare credit card, never synced, no payment category.
    card = _make_account(test_user.id, name="Loose Card", type="credit", subtype="credit card")
    categories_before = Category.query.filter_by(user_id=test_user.id).count()

    # Act
    response = _patch_account(client, auth_headers, card.id, debt_payoff=True)

    # Assert
    assert response.status_code == 200
    assert response.get_json()["account"]["debt_payoff"] is True
    assert Category.query.filter_by(user_id=test_user.id).count() == categories_before


def test_patch_account_debt_payoff_true_is_idempotent(client, test_user, auth_headers, credit_account):
    # Arrange
    card, payment_cat, group = credit_account

    # Act — set it twice.
    first = _patch_account(client, auth_headers, card.id, debt_payoff=True)
    converted_parent_after_first = db.session.get(Category, payment_cat.id).parent_id
    second = _patch_account(client, auth_headers, card.id, debt_payoff=True)

    # Assert — second call is a no-op, not a second conversion or an error.
    assert first.status_code == 200
    assert second.status_code == 200
    assert converted_parent_after_first is None
    assert db.session.get(Category, payment_cat.id).parent_id is None
    assert db.session.get(Category, group.id).archived is True
    # No duplicate / resurrected payment category.
    assert Category.query.filter_by(payment_account_id=card.id).count() == 0


def test_patch_account_can_clear_debt_payoff(client, test_user, auth_headers):
    # Arrange
    card = _make_account(test_user.id, name="Rewards Card", type="credit", subtype="credit card")
    _patch_account(client, auth_headers, card.id, debt_payoff=True)

    # Act
    response = _patch_account(client, auth_headers, card.id, debt_payoff=False)

    # Assert
    assert response.status_code == 200
    assert response.get_json()["account"]["debt_payoff"] is False


def test_patch_account_without_token_returns_401(client, test_user):
    # Arrange
    card = _make_account(test_user.id, name="Rewards Card", type="credit", subtype="credit card")

    # Act
    response = client.patch(f"/api/accounts/{card.id}", json={"debt_payoff": True})

    # Assert
    assert response.status_code == 401


def test_patch_account_not_owned_returns_404(client, test_user, auth_headers):
    # Arrange — another user's credit card.
    other = User(username="accounts-patch-other", password_hash=generate_password_hash("irrelevant"))
    db.session.add(other)
    db.session.commit()
    theirs = _make_account(other.id, name="Not Yours", type="credit", subtype="credit card")

    # Act
    response = _patch_account(client, auth_headers, theirs.id, debt_payoff=True)

    # Assert — 404 for a foreign row and for an unknown id alike (no
    # existence leak), and the foreign row's flag is untouched.
    assert response.status_code == 404
    assert _patch_account(client, auth_headers, 999999, debt_payoff=True).status_code == 404
    assert db.session.get(Account, theirs.id).debt_payoff is False


def test_patch_account_non_credit_type_returns_400(client, test_user, auth_headers):
    # Arrange — a depository account can't be a debt-payoff card.
    checking = _make_account(test_user.id, name="Checking", type="depository", subtype="checking")

    # Act
    response = _patch_account(client, auth_headers, checking.id, debt_payoff=True)

    # Assert
    assert response.status_code == 400
    assert db.session.get(Account, checking.id).debt_payoff is False


def test_patch_account_non_boolean_debt_payoff_returns_400(client, test_user, auth_headers):
    # Arrange
    card = _make_account(test_user.id, name="Rewards Card", type="credit", subtype="credit card")

    # Act / Assert — a string, a number, and an absent field are all rejected.
    assert client.patch(
        f"/api/accounts/{card.id}", json={"debt_payoff": "true"}, headers=auth_headers
    ).status_code == 400
    assert client.patch(
        f"/api/accounts/{card.id}", json={"debt_payoff": 1}, headers=auth_headers
    ).status_code == 400
    assert client.patch(
        f"/api/accounts/{card.id}", json={}, headers=auth_headers
    ).status_code == 400
    assert db.session.get(Account, card.id).debt_payoff is False
