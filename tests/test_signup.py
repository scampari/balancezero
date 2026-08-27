"""Integration tests for spec/signup.md — invite-only account creation.

Every test here traces to a case in spec/signup.md's integration test
contract. Do not add cases here that aren't in the spec — extend the spec
first.
"""

from datetime import datetime, timedelta

from conftest import INVITE_CODE, TEST_PASSWORD, TEST_USERNAME
from models import InviteCode, User, db

VALID_PASSWORD = "a-good-long-password"


# ---------------------------------------------------------------------------
# POST /api/signup — happy path
# ---------------------------------------------------------------------------


def test_signup_with_valid_invite_creates_user_and_logs_in(client, invite_code):
    # Act
    response = client.post(
        "/api/signup",
        json={"username": "newbie", "password": VALID_PASSWORD, "invite_code": INVITE_CODE},
    )

    # Assert
    assert response.status_code == 201
    body = response.get_json()
    assert isinstance(body["access_token"], str) and body["access_token"]

    set_cookie_headers = response.headers.getlist("Set-Cookie")
    refresh_cookie_header = next(h for h in set_cookie_headers if "refresh" in h.lower())
    assert "HttpOnly" in refresh_cookie_header
    assert "Secure" in refresh_cookie_header
    assert "SameSite=Strict" in refresh_cookie_header

    assert User.query.filter_by(username="newbie").first() is not None


def test_signup_marks_invite_code_used(client, invite_code):
    # Act
    client.post(
        "/api/signup",
        json={"username": "newbie", "password": VALID_PASSWORD, "invite_code": INVITE_CODE},
    )

    # Assert
    db.session.refresh(invite_code)
    new_user = User.query.filter_by(username="newbie").first()
    assert invite_code.used_at is not None
    assert invite_code.used_by_user_id == new_user.id


def test_signup_created_user_is_not_demo(client, invite_code):
    # Act
    client.post(
        "/api/signup",
        json={"username": "newbie", "password": VALID_PASSWORD, "invite_code": INVITE_CODE},
    )

    # Assert
    assert User.query.filter_by(username="newbie").first().is_demo is False


def test_signup_created_user_can_then_log_in(client, invite_code):
    # Arrange
    client.post(
        "/api/signup",
        json={"username": "newbie", "password": VALID_PASSWORD, "invite_code": INVITE_CODE},
    )

    # Act
    response = client.post("/api/login", json={"username": "newbie", "password": VALID_PASSWORD})

    # Assert
    assert response.status_code == 200
    assert response.get_json()["access_token"]


def test_signup_stores_email_when_supplied(client, invite_code):
    # Act
    client.post(
        "/api/signup",
        json={
            "username": "newbie",
            "password": VALID_PASSWORD,
            "invite_code": INVITE_CODE,
            "email": "newbie@example.com",
        },
    )

    # Assert
    assert User.query.filter_by(username="newbie").first().email == "newbie@example.com"


def test_signup_omits_email_when_not_supplied(client, invite_code):
    # Act
    client.post(
        "/api/signup",
        json={"username": "newbie", "password": VALID_PASSWORD, "invite_code": INVITE_CODE},
    )

    # Assert
    assert User.query.filter_by(username="newbie").first().email is None


# ---------------------------------------------------------------------------
# POST /api/signup — validation errors
# ---------------------------------------------------------------------------


def test_signup_missing_username_returns_400(client, invite_code):
    response = client.post(
        "/api/signup", json={"password": VALID_PASSWORD, "invite_code": INVITE_CODE}
    )
    assert response.status_code == 400


def test_signup_missing_password_returns_400(client, invite_code):
    response = client.post("/api/signup", json={"username": "newbie", "invite_code": INVITE_CODE})
    assert response.status_code == 400


def test_signup_missing_invite_code_returns_400(client, invite_code):
    response = client.post(
        "/api/signup", json={"username": "newbie", "password": VALID_PASSWORD}
    )
    assert response.status_code == 400


def test_signup_missing_field_does_not_consume_invite_code(client, invite_code):
    # Act — a request missing the password
    client.post("/api/signup", json={"username": "newbie", "invite_code": INVITE_CODE})

    # Assert — the code is still usable
    db.session.refresh(invite_code)
    assert invite_code.used_at is None


def test_signup_short_password_returns_400(client, invite_code):
    response = client.post(
        "/api/signup",
        json={"username": "newbie", "password": "short", "invite_code": INVITE_CODE},
    )
    assert response.status_code == 400
    assert User.query.filter_by(username="newbie").first() is None


def test_signup_too_long_password_returns_400(client, invite_code):
    response = client.post(
        "/api/signup",
        json={"username": "newbie", "password": "x" * 129, "invite_code": INVITE_CODE},
    )
    assert response.status_code == 400
    assert User.query.filter_by(username="newbie").first() is None


# ---------------------------------------------------------------------------
# POST /api/signup — invite-code errors
# ---------------------------------------------------------------------------


def test_signup_unknown_invite_code_returns_403(client):
    response = client.post(
        "/api/signup",
        json={"username": "newbie", "password": VALID_PASSWORD, "invite_code": "nope"},
    )
    assert response.status_code == 403
    assert User.query.filter_by(username="newbie").first() is None


def test_signup_used_invite_code_returns_403(client, invite_code):
    # Arrange — consume the code
    client.post(
        "/api/signup",
        json={"username": "first", "password": VALID_PASSWORD, "invite_code": INVITE_CODE},
    )

    # Act — a second signup with the same code
    response = client.post(
        "/api/signup",
        json={"username": "second", "password": VALID_PASSWORD, "invite_code": INVITE_CODE},
    )

    # Assert
    assert response.status_code == 403
    assert User.query.filter_by(username="second").first() is None


def test_signup_expired_invite_code_returns_403(client):
    # Arrange
    expired = InviteCode(code="expired-code", expires_at=datetime.utcnow() - timedelta(days=1))
    db.session.add(expired)
    db.session.commit()

    # Act
    response = client.post(
        "/api/signup",
        json={"username": "newbie", "password": VALID_PASSWORD, "invite_code": "expired-code"},
    )

    # Assert
    assert response.status_code == 403
    assert User.query.filter_by(username="newbie").first() is None


def test_signup_invalid_codes_share_one_generic_message(client, invite_code):
    # Arrange — consume the valid code so it's now "used"
    client.post(
        "/api/signup",
        json={"username": "first", "password": VALID_PASSWORD, "invite_code": INVITE_CODE},
    )

    # Act
    unknown = client.post(
        "/api/signup",
        json={"username": "a", "password": VALID_PASSWORD, "invite_code": "does-not-exist"},
    )
    used = client.post(
        "/api/signup",
        json={"username": "b", "password": VALID_PASSWORD, "invite_code": INVITE_CODE},
    )

    # Assert — a probe can't tell "wrong code" from "already used"
    assert unknown.status_code == used.status_code == 403
    assert unknown.get_json() == used.get_json()


# ---------------------------------------------------------------------------
# POST /api/signup — conflict errors
# ---------------------------------------------------------------------------


def test_signup_taken_username_returns_409(client, invite_code, test_user):
    # test_user fixture already created TEST_USERNAME
    response = client.post(
        "/api/signup",
        json={"username": TEST_USERNAME, "password": VALID_PASSWORD, "invite_code": INVITE_CODE},
    )
    assert response.status_code == 409


def test_signup_taken_username_does_not_consume_invite_code(client, invite_code, test_user):
    # Act
    client.post(
        "/api/signup",
        json={"username": TEST_USERNAME, "password": VALID_PASSWORD, "invite_code": INVITE_CODE},
    )

    # Assert — the visitor can retry with a different name
    db.session.refresh(invite_code)
    assert invite_code.used_at is None


def test_signup_taken_email_returns_409(client, invite_code):
    # Arrange — an existing user owns the email
    db.session.add(
        User(username="owner", password_hash="x", email="taken@example.com")
    )
    db.session.commit()

    # Act
    response = client.post(
        "/api/signup",
        json={
            "username": "newbie",
            "password": VALID_PASSWORD,
            "invite_code": INVITE_CODE,
            "email": "taken@example.com",
        },
    )

    # Assert
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Rate limiting — POST /api/login and POST /api/signup
# ---------------------------------------------------------------------------


def test_signup_rate_limited_after_threshold_returns_429(client):
    # Act — 5 signup attempts are allowed per window; the 6th is throttled
    for _ in range(5):
        client.post("/api/signup", json={"username": "x", "password": VALID_PASSWORD, "invite_code": "no"})

    response = client.post(
        "/api/signup", json={"username": "x", "password": VALID_PASSWORD, "invite_code": "no"}
    )

    # Assert
    assert response.status_code == 429


def test_login_rate_limited_after_threshold_returns_429(client, test_user):
    # Act — 10 login attempts are allowed per window; the 11th is throttled
    for _ in range(10):
        client.post("/api/login", json={"username": TEST_USERNAME, "password": "wrong"})

    response = client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})

    # Assert — even a correct password is refused once the window is exhausted
    assert response.status_code == 429
