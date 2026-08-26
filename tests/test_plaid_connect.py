"""Integration tests for spec/plaid-connect.md.

Hits Plaid's real Sandbox API rather than mocking, per spec/plaid-connect.md's
Notes and context/testing.md's Plaid Sandbox entry: unlike SimpleFIN's demo
bridge (a one-time-claim resource that got exhausted by repeated automated
test runs during that slice's own development), Plaid Sandbox is built for
exactly this — unlimited test Items, default credentials that work
repeatedly, and /sandbox/public_token/create to generate a fresh
public_token per test without ever touching the Link UI.

Requires real PLAID_CLIENT_ID / PLAID_SECRET (Sandbox) credentials in the
environment. Three tests that specifically exercise a real successful
exchange (test_connect_with_valid_public_token_succeeds,
test_reconnect_replaces_existing_connection,
test_status_returns_true_after_connecting) are skipped when those aren't
present — see `requires_plaid_sandbox` below. Every other test hits our own
(not-yet-implemented) routes directly and needs no live Plaid call at all.
"""

import os

import plaid
import pytest
from models import db
from plaid.api import plaid_api
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest

# Plaid's standard Sandbox test institution ("First Platypus Bank"). Verify
# against current Plaid docs if this ever needs changing — not re-verified
# with the same rigor as the SDK call shapes themselves (see plan's research).
SANDBOX_INSTITUTION_ID = "ins_109508"

_HAS_PLAID_SANDBOX_CREDENTIALS = bool(os.environ.get("PLAID_CLIENT_ID")) and bool(os.environ.get("PLAID_SECRET"))

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


def _create_sandbox_public_token():
    """Real call to Plaid Sandbox — generates a fresh, valid public_token
    without touching the Link UI. Safe to call repeatedly (see module
    docstring); each call produces a token usable exactly once for exchange,
    same as a real Link completion would."""
    request = SandboxPublicTokenCreateRequest(
        institution_id=SANDBOX_INSTITUTION_ID,
        initial_products=[Products("transactions")],
    )
    response = _plaid_sandbox_client().sandbox_public_token_create(request)
    return response["public_token"]


# ---------------------------------------------------------------------------
# POST /api/plaid/link-token
# ---------------------------------------------------------------------------


def test_link_token_created_for_authenticated_user(client, test_user, auth_headers):
    # Act
    response = client.post("/api/plaid/link-token", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert "link_token" in response.get_json()


def test_link_token_denied_for_demo_user(client, demo_auth_headers):
    # Act
    response = client.post("/api/plaid/link-token", headers=demo_auth_headers)

    # Assert
    assert response.status_code == 403


def test_link_token_without_token_returns_401(client, test_user):
    # Act
    response = client.post("/api/plaid/link-token")

    # Assert
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/plaid/connect
# ---------------------------------------------------------------------------


@requires_plaid_sandbox
def test_connect_with_valid_public_token_succeeds(client, test_user, auth_headers):
    # Arrange — a real, fresh public_token from Plaid Sandbox
    public_token = _create_sandbox_public_token()

    # Act
    response = client.post("/api/plaid/connect", json={"public_token": public_token}, headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert response.get_json() == {"status": "connected"}

    # Assert side effect — encrypted, not plaintext; item_id stored too
    db.session.refresh(test_user)
    assert test_user.plaid_access_token_encrypted is not None
    assert test_user.plaid_item_id is not None


def test_connect_without_token_returns_401(client, test_user):
    # Act — placeholder public_token is fine, the auth check happens first
    response = client.post("/api/plaid/connect", json={"public_token": "placeholder"})

    # Assert
    assert response.status_code == 401


def test_connect_as_demo_user_returns_403(client, demo_auth_headers):
    # Act
    response = client.post(
        "/api/plaid/connect", json={"public_token": "placeholder"}, headers=demo_auth_headers
    )

    # Assert
    assert response.status_code == 403


def test_connect_missing_public_token_returns_400(client, test_user, auth_headers):
    # Act
    response = client.post("/api/plaid/connect", json={}, headers=auth_headers)

    # Assert
    assert response.status_code == 400


def test_connect_with_invalid_public_token_returns_502(client, test_user, auth_headers):
    # Act — syntactically-plausible but fake public_token; Plaid rejects it
    response = client.post(
        "/api/plaid/connect", json={"public_token": "public-sandbox-not-a-real-token"}, headers=auth_headers
    )

    # Assert — sanitized error, not Plaid's raw response relayed
    assert response.status_code == 502
    body = response.get_json()
    assert "error" in body


@requires_plaid_sandbox
def test_reconnect_replaces_existing_connection(client, test_user, auth_headers):
    # Arrange — connect once already
    first_token = _create_sandbox_public_token()
    client.post("/api/plaid/connect", json={"public_token": first_token}, headers=auth_headers)
    db.session.refresh(test_user)
    first_stored_value = test_user.plaid_access_token_encrypted

    # Act — connect again with a fresh public_token (a real one only exchanges once)
    second_token = _create_sandbox_public_token()
    response = client.post("/api/plaid/connect", json={"public_token": second_token}, headers=auth_headers)

    # Assert — succeeds, not a conflict
    assert response.status_code == 200
    db.session.refresh(test_user)
    assert test_user.plaid_access_token_encrypted != first_stored_value


# ---------------------------------------------------------------------------
# GET /api/plaid/status
# ---------------------------------------------------------------------------


def test_status_returns_false_when_not_connected(client, test_user, auth_headers):
    # Act
    response = client.get("/api/plaid/status", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert response.get_json() == {"connected": False}


@requires_plaid_sandbox
def test_status_returns_true_after_connecting(client, test_user, auth_headers):
    # Arrange
    public_token = _create_sandbox_public_token()
    client.post("/api/plaid/connect", json={"public_token": public_token}, headers=auth_headers)

    # Act
    response = client.get("/api/plaid/status", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert response.get_json() == {"connected": True}


def test_status_without_token_returns_401(client, test_user):
    # Act
    response = client.get("/api/plaid/status")

    # Assert
    assert response.status_code == 401
