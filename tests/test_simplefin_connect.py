"""Integration tests for spec/simplefin-connect.md.

Hits SimpleFIN's real, public, reusable demo bridge — no mocking of the
exchange itself, per context/testing.md's "prefer real over mocked" default.
Requires network access to reach beta-bridge.simplefin.org.
"""

import base64

from models import User, db

DEMO_SETUP_TOKEN = "aHR0cHM6Ly9iZXRhLWJyaWRnZS5zaW1wbGVmaW4ub3JnL3NpbXBsZWZpbi9jbGFpbS9ERU1PLXYyLUE4MEVDOUI5NDlGMjQxOEE0QzhE"


# ---------------------------------------------------------------------------
# POST /api/simplefin/connect
# ---------------------------------------------------------------------------


def test_connect_with_real_demo_token_succeeds(client, test_user, auth_headers):
    # Act
    response = client.post(
        "/api/simplefin/connect", json={"setup_token": DEMO_SETUP_TOKEN}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 200
    assert response.get_json() == {"status": "connected"}

    # Assert side effect — encrypted, not plaintext, not just re-encoded
    db.session.refresh(test_user)
    stored = test_user.simplefin_access_url_encrypted
    assert stored is not None
    assert b"beta-bridge.simplefin.org" not in stored
    assert b"demo:demo" not in stored


def test_connect_without_token_returns_401(client, test_user):
    # Act
    response = client.post("/api/simplefin/connect", json={"setup_token": DEMO_SETUP_TOKEN})

    # Assert
    assert response.status_code == 401


def test_connect_as_demo_user_returns_403(client, demo_auth_headers):
    # Act
    response = client.post(
        "/api/simplefin/connect", json={"setup_token": DEMO_SETUP_TOKEN}, headers=demo_auth_headers
    )

    # Assert
    assert response.status_code == 403


def test_connect_missing_setup_token_returns_400(client, test_user, auth_headers):
    # Act
    response = client.post("/api/simplefin/connect", json={}, headers=auth_headers)

    # Assert
    assert response.status_code == 400


def test_connect_invalid_base64_returns_400(client, test_user, auth_headers):
    # Act
    response = client.post(
        "/api/simplefin/connect", json={"setup_token": "not valid base64!!!"}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 400


def test_connect_non_https_decoded_url_returns_400(client, test_user, auth_headers):
    # Arrange — valid base64, but decodes to a non-https URL
    sneaky_token = base64.b64encode(b"http://internal.local/claim/x").decode()

    # Act
    response = client.post(
        "/api/simplefin/connect", json={"setup_token": sneaky_token}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 400


def test_connect_with_bad_claim_url_returns_502(client, test_user, auth_headers):
    # Arrange — valid base64, valid https URL, but not a real SimpleFIN claim endpoint
    bad_token = base64.b64encode(b"https://beta-bridge.simplefin.org/simplefin/claim/NOT-A-REAL-TOKEN").decode()

    # Act
    response = client.post(
        "/api/simplefin/connect", json={"setup_token": bad_token}, headers=auth_headers
    )

    # Assert — sanitized error, not SimpleFIN's raw response relayed
    assert response.status_code == 502
    body = response.get_json()
    assert "error" in body


def test_reconnect_replaces_existing_connection(client, test_user, auth_headers):
    # Arrange — connect once already
    client.post("/api/simplefin/connect", json={"setup_token": DEMO_SETUP_TOKEN}, headers=auth_headers)
    db.session.refresh(test_user)
    first_stored_value = test_user.simplefin_access_url_encrypted

    # Act — connect again
    response = client.post(
        "/api/simplefin/connect", json={"setup_token": DEMO_SETUP_TOKEN}, headers=auth_headers
    )

    # Assert — succeeds, not a conflict
    assert response.status_code == 200
    db.session.refresh(test_user)
    # Fernet encryption is non-deterministic (includes a random IV/timestamp),
    # so re-encrypting the same underlying URL still produces different bytes.
    assert test_user.simplefin_access_url_encrypted != first_stored_value


# ---------------------------------------------------------------------------
# GET /api/simplefin/status
# ---------------------------------------------------------------------------


def test_status_returns_false_when_not_connected(client, test_user, auth_headers):
    # Act
    response = client.get("/api/simplefin/status", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert response.get_json() == {"connected": False}


def test_status_returns_true_after_connecting(client, test_user, auth_headers):
    # Arrange
    client.post("/api/simplefin/connect", json={"setup_token": DEMO_SETUP_TOKEN}, headers=auth_headers)

    # Act
    response = client.get("/api/simplefin/status", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert response.get_json() == {"connected": True}


def test_status_without_token_returns_401(client, test_user):
    # Act
    response = client.get("/api/simplefin/status")

    # Assert
    assert response.status_code == 401
