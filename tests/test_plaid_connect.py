"""Integration tests for spec/plaid-connect.md (multi-institution, changes/008).

Hits Plaid's real Sandbox API for the exchange happy-paths, per
context/testing.md's Plaid Sandbox entry (unlimited test Items, repeatable).
The re-link-in-place branch and the DELETE route are exercised with a
seeded PlaidItem + a stubbed Plaid client, because live Sandbox can't be
made to re-exchange the same item_id (every sandbox_public_token_create
mints a fresh Item).

Requires real PLAID_CLIENT_ID / PLAID_SECRET (Sandbox) for the
@requires_plaid_sandbox tests; the rest run offline.
"""

import os

import plaid
import pytest
from cryptography.fernet import Fernet
from models import Account, PlaidItem, User, db
from plaid.api import plaid_api
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from werkzeug.security import generate_password_hash

SANDBOX_INSTITUTION_ID = "ins_109508"  # First Platypus Bank
SANDBOX_INSTITUTION_ID_2 = "ins_109509"  # First Gingham Credit Union

_PLACEHOLDER_PLAID_CLIENT_ID = "test-placeholder-client-id"
_PLACEHOLDER_PLAID_SECRET = "test-placeholder-secret"
_HAS_PLAID_SANDBOX_CREDENTIALS = (
    os.environ.get("PLAID_CLIENT_ID") not in (None, _PLACEHOLDER_PLAID_CLIENT_ID)
    and os.environ.get("PLAID_SECRET") not in (None, _PLACEHOLDER_PLAID_SECRET)
)

requires_plaid_sandbox = pytest.mark.skipif(
    not _HAS_PLAID_SANDBOX_CREDENTIALS,
    reason="requires real PLAID_CLIENT_ID/PLAID_SECRET Sandbox credentials, not present in this environment",
)


def _plaid_sandbox_client():
    configuration = plaid.Configuration(
        host=plaid.Environment.Sandbox,
        api_key={"clientId": os.environ["PLAID_CLIENT_ID"], "secret": os.environ["PLAID_SECRET"]},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def _create_sandbox_public_token(institution_id=SANDBOX_INSTITUTION_ID):
    request = SandboxPublicTokenCreateRequest(
        institution_id=institution_id,
        initial_products=[Products("transactions")],
    )
    return _plaid_sandbox_client().sandbox_public_token_create(request)["public_token"]


class _StubExchangeClient:
    """Returns a fixed item_id so the re-link-in-place branch can be tested
    without a live Sandbox re-exchange."""

    def __init__(self, item_id, access_token="access-sandbox-second"):
        self._item_id = item_id
        self._access_token = access_token

    def item_public_token_exchange(self, _request):
        return {"access_token": self._access_token, "item_id": self._item_id}

    def item_remove(self, _request):
        return {"request_id": "stub"}


def _stub_plaid(monkeypatch, stub):
    import plaid_api as plaid_api_module

    monkeypatch.setattr(plaid_api_module, "_plaid_client", lambda: stub)


# ---------------------------------------------------------------------------
# POST /api/plaid/link-token
# ---------------------------------------------------------------------------


@requires_plaid_sandbox
def test_link_token_created_for_authenticated_user(client, test_user, auth_headers):
    response = client.post("/api/plaid/link-token", headers=auth_headers)
    assert response.status_code == 200
    assert "link_token" in response.get_json()


def test_link_token_denied_for_demo_user(client, demo_auth_headers):
    assert client.post("/api/plaid/link-token", headers=demo_auth_headers).status_code == 403


def test_link_token_without_token_returns_401(client, test_user):
    assert client.post("/api/plaid/link-token").status_code == 401


# ---------------------------------------------------------------------------
# POST /api/plaid/connect
# ---------------------------------------------------------------------------


@requires_plaid_sandbox
def test_connect_creates_a_plaid_item(client, test_user, auth_headers):
    # Act
    response = client.post(
        "/api/plaid/connect",
        json={"public_token": _create_sandbox_public_token(), "institution_name": "First Platypus Bank"},
        headers=auth_headers,
    )

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "connected"
    assert body["item"]["institution_name"] == "First Platypus Bank"
    assert "access_token" not in body["item"]  # never leaked

    # Side effect — exactly one PlaidItem, token encrypted, item id stored
    items = PlaidItem.query.filter_by(user_id=test_user.id).all()
    assert len(items) == 1
    assert items[0].plaid_item_id
    assert items[0].access_token_encrypted not in (None, b"", items[0].plaid_item_id.encode())
    assert items[0].institution_name == "First Platypus Bank"


@requires_plaid_sandbox
def test_connect_second_institution_adds_a_second_item(client, test_user, auth_headers):
    # Arrange — one institution already linked
    client.post(
        "/api/plaid/connect",
        json={"public_token": _create_sandbox_public_token(SANDBOX_INSTITUTION_ID)},
        headers=auth_headers,
    )

    # Act — link a different institution
    response = client.post(
        "/api/plaid/connect",
        json={"public_token": _create_sandbox_public_token(SANDBOX_INSTITUTION_ID_2)},
        headers=auth_headers,
    )

    # Assert — two distinct rows, not a replace
    assert response.status_code == 200
    items = PlaidItem.query.filter_by(user_id=test_user.id).all()
    assert len(items) == 2
    assert len({i.plaid_item_id for i in items}) == 2


def test_reconnect_same_item_updates_in_place(client, test_user, auth_headers, plaid_item, monkeypatch):
    # Arrange — plaid_item fixture already linked "test-item-id"; stub the
    # exchange to return that same item id (a token repair / re-Link run).
    original_token = plaid_item.access_token_encrypted
    _stub_plaid(monkeypatch, _StubExchangeClient(item_id="test-item-id"))

    # Act
    response = client.post(
        "/api/plaid/connect",
        json={"public_token": "public-sandbox-anything", "institution_name": "Renamed Bank"},
        headers=auth_headers,
    )

    # Assert — still one row, token refreshed, name updated
    assert response.status_code == 200
    items = PlaidItem.query.filter_by(user_id=test_user.id).all()
    assert len(items) == 1
    db.session.refresh(items[0])
    assert items[0].access_token_encrypted != original_token
    assert items[0].institution_name == "Renamed Bank"


def test_connect_without_token_returns_401(client, test_user):
    assert client.post("/api/plaid/connect", json={"public_token": "x"}).status_code == 401


def test_connect_as_demo_user_returns_403(client, demo_auth_headers):
    response = client.post("/api/plaid/connect", json={"public_token": "x"}, headers=demo_auth_headers)
    assert response.status_code == 403


def test_connect_missing_public_token_returns_400(client, test_user, auth_headers):
    assert client.post("/api/plaid/connect", json={}, headers=auth_headers).status_code == 400


def test_connect_with_invalid_public_token_returns_502(client, test_user, auth_headers):
    response = client.post(
        "/api/plaid/connect",
        json={"public_token": "public-sandbox-not-a-real-token"},
        headers=auth_headers,
    )
    assert response.status_code == 502
    assert "error" in response.get_json()


# ---------------------------------------------------------------------------
# GET /api/plaid/status
# ---------------------------------------------------------------------------


def test_status_lists_linked_institutions_with_account_counts(client, test_user, auth_headers, plaid_item):
    # Arrange — two accounts under the linked item
    db.session.add_all(
        [
            Account(user_id=test_user.id, name="Checking", plaid_account_id="a1", plaid_item_id=plaid_item.id),
            Account(user_id=test_user.id, name="Savings", plaid_account_id="a2", plaid_item_id=plaid_item.id),
        ]
    )
    db.session.commit()

    # Act
    response = client.get("/api/plaid/status", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    items = response.get_json()["items"]
    assert len(items) == 1
    assert items[0]["institution_name"] == "First Platypus Bank"
    assert items[0]["account_count"] == 2
    assert items[0]["last_synced"] is None
    assert "access_token" not in items[0]


def test_status_empty_when_not_connected(client, test_user, auth_headers):
    response = client.get("/api/plaid/status", headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json() == {"items": []}


def test_status_without_token_returns_401(client, test_user):
    assert client.get("/api/plaid/status").status_code == 401


def test_status_uses_generic_label_when_institution_name_missing(client, test_user, auth_headers):
    db.session.add(
        PlaidItem(
            user_id=test_user.id,
            plaid_item_id="unnamed-item",
            access_token_encrypted=b"x",
        )
    )
    db.session.commit()
    items = client.get("/api/plaid/status", headers=auth_headers).get_json()["items"]
    assert items[0]["institution_name"] == "Linked bank"


# ---------------------------------------------------------------------------
# DELETE /api/plaid/items/<id>
# ---------------------------------------------------------------------------


def test_remove_item_deletes_it_but_keeps_accounts(client, test_user, auth_headers, plaid_item, monkeypatch):
    # Arrange — an account (with a transaction) under the item
    _stub_plaid(monkeypatch, _StubExchangeClient(item_id="test-item-id"))
    account = Account(
        user_id=test_user.id, name="Checking", plaid_account_id="a1", plaid_item_id=plaid_item.id
    )
    db.session.add(account)
    db.session.commit()
    account_id = account.id
    item_id = plaid_item.id

    # Act
    response = client.delete(f"/api/plaid/items/{item_id}", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert response.get_json() == {"status": "removed"}
    assert db.session.get(PlaidItem, item_id) is None
    kept = db.session.get(Account, account_id)
    assert kept is not None
    db.session.refresh(kept)
    assert kept.plaid_item_id is None  # ON DELETE SET NULL


def test_remove_unknown_item_returns_404(client, test_user, auth_headers):
    assert client.delete("/api/plaid/items/999999", headers=auth_headers).status_code == 404


def test_remove_other_users_item_returns_403(client, test_user, auth_headers):
    other = User(username="other", password_hash=generate_password_hash("x" * 12))
    db.session.add(other)
    db.session.flush()
    theirs = PlaidItem(user_id=other.id, plaid_item_id="theirs", access_token_encrypted=b"x")
    db.session.add(theirs)
    db.session.commit()

    response = client.delete(f"/api/plaid/items/{theirs.id}", headers=auth_headers)
    assert response.status_code == 403
    assert db.session.get(PlaidItem, theirs.id) is not None


def test_remove_item_as_demo_returns_403(client, demo_auth_headers):
    assert client.delete("/api/plaid/items/1", headers=demo_auth_headers).status_code == 403
