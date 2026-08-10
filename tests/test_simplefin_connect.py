"""Integration tests for spec/simplefin-connect.md.

Mocks the outbound claim-URL exchange at the HTTP client layer (requests.post)
rather than hitting SimpleFIN's real demo bridge — see spec/simplefin-connect.md's
Notes for why: the demo token's "reusable" claim didn't hold up empirically
under a real test suite's repeated automated runs (it returned "already
claimed" / 403 after a handful of real exchanges during this slice's own
development). The mock is scoped tightly to the one outbound call this code
makes, so everything else (route logic, encryption, error handling) still
runs for real.
"""

import base64
from unittest.mock import Mock, patch

import requests
from models import User, db

DEMO_SETUP_TOKEN = "aHR0cHM6Ly9iZXRhLWJyaWRnZS5zaW1wbGVmaW4ub3JnL3NpbXBsZWZpbi9jbGFpbS9ERU1PLXYyLUE4MEVDOUI5NDlGMjQxOEE0QzhE"
FAKE_ACCESS_URL = "https://demo:demo@beta-bridge.simplefin.org/simplefin"


def _mock_successful_exchange():
    response = Mock()
    response.status_code = 200
    response.raw.read.return_value = FAKE_ACCESS_URL.encode("utf-8")
    return patch("simplefin_api.requests.post", return_value=response)


def _mock_failed_exchange():
    return patch("simplefin_api.requests.post", side_effect=requests.RequestException("simulated failure"))


def _mock_redirect_exchange():
    """Simulates a compromised/malicious claim endpoint trying to redirect the
    request elsewhere — allow_redirects=False means requests won't follow it,
    so this should surface as an ordinary failure, not a followed redirect."""
    response = Mock()
    response.status_code = 302
    return patch("simplefin_api.requests.post", return_value=response)


def _mock_oversized_exchange():
    response = Mock()
    response.status_code = 200
    response.raw.read.return_value = b"x" * 5000  # over MAX_CLAIM_RESPONSE_BYTES
    return patch("simplefin_api.requests.post", return_value=response)


def _mock_malformed_body_exchange():
    """A 200 response whose body doesn't look like an access URL at all —
    e.g. a compromised endpoint trying to poison the stored credential."""
    response = Mock()
    response.status_code = 200
    response.raw.read.return_value = b"not a url"
    return patch("simplefin_api.requests.post", return_value=response)


# ---------------------------------------------------------------------------
# POST /api/simplefin/connect
# ---------------------------------------------------------------------------


def test_connect_with_valid_token_succeeds(client, test_user, auth_headers):
    # Act
    with _mock_successful_exchange():
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


def test_connect_https_but_untrusted_domain_returns_400(client, test_user, auth_headers):
    # Arrange — https, valid URL shape, but not a SimpleFIN Bridge domain.
    # SSRF defense: the https-only check alone doesn't stop a token aimed at
    # an internal or third-party host.
    ssrf_token = base64.b64encode(b"https://169.254.169.254/claim/x").decode()

    # Act
    response = client.post(
        "/api/simplefin/connect", json={"setup_token": ssrf_token}, headers=auth_headers
    )

    # Assert
    assert response.status_code == 400


def test_connect_exchange_redirect_is_not_followed(client, test_user, auth_headers):
    # Act — a compromised claim endpoint tries to redirect elsewhere
    with _mock_redirect_exchange():
        response = client.post(
            "/api/simplefin/connect", json={"setup_token": DEMO_SETUP_TOKEN}, headers=auth_headers
        )

    # Assert — surfaces as an ordinary failure, not a followed redirect
    assert response.status_code == 502


def test_connect_oversized_response_returns_502(client, test_user, auth_headers):
    # Act
    with _mock_oversized_exchange():
        response = client.post(
            "/api/simplefin/connect", json={"setup_token": DEMO_SETUP_TOKEN}, headers=auth_headers
        )

    # Assert
    assert response.status_code == 502


def test_connect_malformed_response_body_returns_502(client, test_user, auth_headers):
    # Act — 200 response, but the body doesn't look like an access URL
    with _mock_malformed_body_exchange():
        response = client.post(
            "/api/simplefin/connect", json={"setup_token": DEMO_SETUP_TOKEN}, headers=auth_headers
        )

    # Assert — not stored, surfaced as a failure
    assert response.status_code == 502
    db.session.refresh(test_user)
    assert test_user.simplefin_access_url_encrypted is None


def test_connect_with_bad_claim_url_returns_502(client, test_user, auth_headers):
    # Arrange — valid base64, valid https URL, but the exchange itself fails
    bad_token = base64.b64encode(b"https://beta-bridge.simplefin.org/simplefin/claim/NOT-A-REAL-TOKEN").decode()

    # Act
    with _mock_failed_exchange():
        response = client.post(
            "/api/simplefin/connect", json={"setup_token": bad_token}, headers=auth_headers
        )

    # Assert — sanitized error, not SimpleFIN's raw response relayed
    assert response.status_code == 502
    body = response.get_json()
    assert "error" in body


def test_reconnect_replaces_existing_connection(client, test_user, auth_headers):
    # Arrange — connect once already
    with _mock_successful_exchange():
        client.post("/api/simplefin/connect", json={"setup_token": DEMO_SETUP_TOKEN}, headers=auth_headers)
    db.session.refresh(test_user)
    first_stored_value = test_user.simplefin_access_url_encrypted

    # Act — connect again
    with _mock_successful_exchange():
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
    with _mock_successful_exchange():
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
