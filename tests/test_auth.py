"""Integration tests for spec/auth.md — JWT login, refresh, logout.

Every test here traces to a case in spec/auth.md's integration test contract.
Do not add cases here that aren't in the spec — extend the spec first.
"""

from conftest import TEST_PASSWORD, TEST_USERNAME


# ---------------------------------------------------------------------------
# POST /api/login
# ---------------------------------------------------------------------------


def test_login_with_valid_credentials_returns_access_token_and_sets_refresh_cookie(client, test_user):
    # Arrange — test_user fixture already created a user with known credentials

    # Act
    response = client.post(
        "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert "access_token" in body
    assert isinstance(body["access_token"], str) and body["access_token"]

    # Assert side effect — refresh token set as an httpOnly, Secure, SameSite=Strict cookie
    set_cookie_headers = response.headers.getlist("Set-Cookie")
    assert any("refresh_token" in h or "refresh" in h.lower() for h in set_cookie_headers), (
        f"expected a refresh-token cookie in Set-Cookie headers, got: {set_cookie_headers}"
    )
    refresh_cookie_header = next(h for h in set_cookie_headers if "refresh" in h.lower())
    assert "HttpOnly" in refresh_cookie_header
    assert "Secure" in refresh_cookie_header
    assert "SameSite=Strict" in refresh_cookie_header

    # Access token must never be set as a cookie — body only, held in memory by the frontend
    assert not any("access_token" in h.lower() and "refresh" not in h.lower() for h in set_cookie_headers)


def test_login_with_wrong_password_returns_401(client, test_user):
    # Arrange — test_user exists with TEST_PASSWORD, we send a different one

    # Act
    response = client.post(
        "/api/login", json={"username": TEST_USERNAME, "password": "wrong-password"}
    )

    # Assert
    assert response.status_code == 401
    assert "access_token" not in (response.get_json() or {})
    assert not response.headers.getlist("Set-Cookie")


def test_login_with_unknown_username_returns_401_with_same_message_as_wrong_password(client, test_user):
    # Arrange
    wrong_password_response = client.post(
        "/api/login", json={"username": TEST_USERNAME, "password": "wrong-password"}
    )

    # Act
    unknown_user_response = client.post(
        "/api/login", json={"username": "no-such-user", "password": "irrelevant"}
    )

    # Assert — same status and same error message, to avoid username enumeration
    assert unknown_user_response.status_code == 401
    assert wrong_password_response.status_code == 401
    assert unknown_user_response.get_json() == wrong_password_response.get_json()


def test_login_missing_username_returns_400(client, test_user):
    # Act
    response = client.post("/api/login", json={"password": TEST_PASSWORD})

    # Assert
    assert response.status_code == 400


def test_login_missing_password_returns_400(client, test_user):
    # Act
    response = client.post("/api/login", json={"username": TEST_USERNAME})

    # Assert
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/refresh
# ---------------------------------------------------------------------------


def test_refresh_with_valid_cookie_returns_new_access_token_and_rotates_cookie(client, test_user):
    # Arrange
    login_response = client.post(
        "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    original_access_token = login_response.get_json()["access_token"]

    # Act — client keeps cookies between requests automatically
    refresh_response = client.post("/api/refresh")

    # Assert
    assert refresh_response.status_code == 200
    new_access_token = refresh_response.get_json()["access_token"]
    assert new_access_token and new_access_token != original_access_token

    # Assert side effect — rotation: a new refresh cookie was issued
    set_cookie_headers = refresh_response.headers.getlist("Set-Cookie")
    assert any("refresh" in h.lower() for h in set_cookie_headers)


def test_refresh_without_cookie_returns_401(client, test_user):
    # Act — fresh client-equivalent call, no prior login in this test
    response = client.post("/api/refresh")

    # Assert
    assert response.status_code == 401


def test_refresh_with_invalid_cookie_returns_401(client, test_user):
    # Arrange
    client.set_cookie("refresh_token", "not-a-real-token")

    # Act
    response = client.post("/api/refresh")

    # Assert
    assert response.status_code == 401


def test_refresh_with_reused_rotated_out_cookie_returns_401(client, test_user):
    # Arrange — log in, capture the original refresh cookie, then refresh once (which rotates it)
    client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
    original_refresh_cookie = client.get_cookie("refresh_token", path="/api")
    client.post("/api/refresh")  # rotates the refresh token

    # Act — reuse the original (now stale) refresh cookie
    client.set_cookie("refresh_token", original_refresh_cookie.value, path="/api")
    reused_response = client.post("/api/refresh")

    # Assert
    assert reused_response.status_code == 401


def test_refresh_with_expired_token_returns_401(client, test_user):
    from datetime import datetime, timedelta

    from freezegun import freeze_time

    # Arrange — log in now, then travel far enough forward that the refresh token has expired
    client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
    future = datetime.utcnow() + timedelta(days=31)

    with freeze_time(future):
        # Act
        response = client.post("/api/refresh")

        # Assert
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/logout
# ---------------------------------------------------------------------------


def test_logout_revokes_refresh_token_so_subsequent_refresh_fails(client, test_user):
    # Arrange
    login_response = client.post(
        "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    access_token = login_response.get_json()["access_token"]

    # Act
    logout_response = client.post(
        "/api/logout", headers={"Authorization": f"Bearer {access_token}"}
    )

    # Assert
    assert logout_response.status_code == 200

    # Assert side effect — this is the actual security-fix proof: the refresh token
    # that survived a copied/replayed cookie under the old session scheme must now
    # be genuinely dead, not just cosmetically logged out.
    post_logout_refresh_response = client.post("/api/refresh")
    assert post_logout_refresh_response.status_code == 401


def test_logout_without_access_token_returns_401(client, test_user):
    # Act — no Authorization header at all
    response = client.post("/api/logout")

    # Assert
    assert response.status_code == 401


def test_logout_with_malformed_access_token_returns_401(client, test_user):
    # Act — covers the protected-route pattern's "malformed/invalid signature" case,
    # exercised here since logout is this slice's only protected route.
    response = client.post("/api/logout", headers={"Authorization": "Bearer not-a-real-jwt"})

    # Assert
    assert response.status_code == 401


def test_logout_with_expired_access_token_returns_401(client, test_user):
    from datetime import datetime, timedelta

    from freezegun import freeze_time

    # Arrange — covers the protected-route pattern's "expired token" case.
    login_response = client.post(
        "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    access_token = login_response.get_json()["access_token"]
    future = datetime.utcnow() + timedelta(minutes=16)

    with freeze_time(future):
        # Act
        response = client.post(
            "/api/logout", headers={"Authorization": f"Bearer {access_token}"}
        )

        # Assert
        assert response.status_code == 401


def test_logout_with_already_revoked_refresh_cookie_still_returns_200(client, test_user):
    # Arrange — log out once already, so the refresh token is already revoked
    login_response = client.post(
        "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    access_token = login_response.get_json()["access_token"]
    client.post("/api/logout", headers={"Authorization": f"Bearer {access_token}"})

    # Act — log out again with the same (still-valid, short-lived) access token
    second_logout_response = client.post(
        "/api/logout", headers={"Authorization": f"Bearer {access_token}"}
    )

    # Assert — idempotent: already logged out is not an error
    assert second_logout_response.status_code == 200


def test_logout_clears_refresh_cookie(client, test_user):
    # Arrange
    login_response = client.post(
        "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    access_token = login_response.get_json()["access_token"]

    # Act
    response = client.post("/api/logout", headers={"Authorization": f"Bearer {access_token}"})

    # Assert — cookie cleared via Max-Age=0 or an Expires date in the past
    set_cookie_headers = response.headers.getlist("Set-Cookie")
    refresh_clear_header = next(h for h in set_cookie_headers if "refresh" in h.lower())
    cleared = "Max-Age=0" in refresh_clear_header or "1970" in refresh_clear_header
    assert cleared, f"expected refresh cookie to be cleared, got: {refresh_clear_header}"
