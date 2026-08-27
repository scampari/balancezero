import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from models import AuthThrottle, InviteCode, RefreshToken, User, db
from starter_categories import create_starter_categories

REFRESH_TOKEN_TTL = timedelta(days=30)

_MIN_PASSWORD_LEN = 10
_MAX_PASSWORD_LEN = 128  # upper bound guards the hash cost against a huge input

# Fixed windows per client IP — see spec/signup.md's rate-limiting section.
# The max-attempt count is configurable (LOGIN_RATE_LIMIT_MAX /
# SIGNUP_RATE_LIMIT_MAX in app.py); both successful and failed attempts count,
# the point being to bound brute force, not to lock accounts.
_LOGIN_RATE_WINDOW = timedelta(minutes=15)
_SIGNUP_RATE_WINDOW = timedelta(minutes=60)

auth_bp = Blueprint("auth_api", __name__, url_prefix="/api")


def register_jwt_error_handlers(jwt_manager):
    """Normalize flask-jwt-extended's default error responses to 401, per
    spec/auth.md's protected-route pattern contract (missing/malformed/expired
    token are all 401 — the library defaults to 422 for a malformed token)."""

    @jwt_manager.unauthorized_loader
    def _missing_token(reason):
        return jsonify({"error": "authorization required"}), 401

    @jwt_manager.invalid_token_loader
    def _invalid_token(reason):
        return jsonify({"error": "invalid token"}), 401

    @jwt_manager.expired_token_loader
    def _expired_token(jwt_header, jwt_payload):
        return jsonify({"error": "token expired"}), 401


def _hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _issue_refresh_token(user_id, commit=True):
    raw_token = secrets.token_urlsafe(32)
    db.session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.utcnow() + REFRESH_TOKEN_TTL,
        )
    )
    if commit:
        db.session.commit()
    return raw_token


def _find_active_refresh_token(raw_token, lock=False):
    if not raw_token:
        return None
    query = RefreshToken.query.filter_by(token_hash=_hash_token(raw_token))
    if lock:
        # Row lock so two concurrent refresh requests with the same cookie can't
        # both pass this check before either revokes it (would mint two token
        # pairs from one old one).
        query = query.with_for_update()
    record = query.first()
    if record is None or record.revoked_at is not None or record.expires_at < datetime.utcnow():
        return None
    return record


def _revoke_refresh_token(record, commit=True):
    record.revoked_at = datetime.utcnow()
    if commit:
        db.session.commit()


_REFRESH_COOKIE_ATTRS = dict(httponly=True, secure=True, samesite="Strict", path="/api")


def _set_refresh_cookie(response, raw_token):
    response.set_cookie(
        "refresh_token", raw_token, max_age=int(REFRESH_TOKEN_TTL.total_seconds()), **_REFRESH_COOKIE_ATTRS
    )


def _clear_refresh_cookie(response):
    response.set_cookie("refresh_token", "", max_age=0, **_REFRESH_COOKIE_ATTRS)


def _origin_is_trusted():
    """Lightweight CSRF guard for the two cookie-touching endpoints (refresh, logout).
    SameSite=Strict already blocks the cookie cross-site in modern browsers; this is
    defense in depth for the endpoints that read it, per spec/auth.md's Notes."""
    allowed_origin = current_app.config.get("ALLOWED_ORIGIN")
    request_origin = request.headers.get("Origin")
    return not (allowed_origin and request_origin and request_origin != allowed_origin)


def require_trusted_origin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _origin_is_trusted():
            return jsonify({"error": "invalid origin"}), 403
        return view(*args, **kwargs)

    return wrapped


def _client_ip():
    """Client address for rate-limit keying. Behind the k3s/Tailscale
    ingress, ProxyFix (gated by TRUSTED_PROXY_COUNT in app.py) rewrites
    request.remote_addr to the real client; with the default of 0 this is
    the direct peer, exactly as before this slice."""
    return request.remote_addr or "unknown"


def _rate_limit_ok(scope, max_attempts, window):
    """Fixed-window counter per (scope, client-IP). Returns False when the
    caller is over the limit for the current window. Both successful and
    failed attempts are counted — see spec/signup.md."""
    key = _client_ip()
    now = datetime.utcnow()

    row = AuthThrottle.query.filter_by(scope=scope, key=key).first()
    if row is None:
        db.session.add(AuthThrottle(scope=scope, key=key, window_start=now, count=1))
        db.session.commit()
        return True

    if now - row.window_start >= window:
        row.window_start = now
        row.count = 1
        db.session.commit()
        return True

    row.count += 1
    db.session.commit()
    return row.count <= max_attempts


def _validate_invite_code(code):
    """Returns the InviteCode row iff it exists, is unused, and is not past
    expiry — otherwise None. Callers must not distinguish the three failure
    modes in the response (see spec/signup.md)."""
    if not code:
        return None
    row = InviteCode.query.filter_by(code=code).first()
    if row is None or row.used_at is not None:
        return None
    if row.expires_at is not None and row.expires_at < datetime.utcnow():
        return None
    return row


@auth_bp.route("/login", methods=["POST"])
def login():
    if not _rate_limit_ok("login", current_app.config["LOGIN_RATE_LIMIT_MAX"], _LOGIN_RATE_WINDOW):
        return jsonify({"error": "too many attempts — try again later"}), 429

    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    user = User.query.filter_by(username=username).first()
    if user is None or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "invalid username or password"}), 401

    access_token = create_access_token(identity=str(user.id))
    raw_refresh_token = _issue_refresh_token(user.id)

    response = jsonify({"access_token": access_token})
    _set_refresh_cookie(response, raw_refresh_token)
    return response, 200


@auth_bp.route("/signup", methods=["POST"])
def signup():
    if not _rate_limit_ok("signup", current_app.config["SIGNUP_RATE_LIMIT_MAX"], _SIGNUP_RATE_WINDOW):
        return jsonify({"error": "too many attempts — try again later"}), 429

    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")
    invite_code = data.get("invite_code")
    email = data.get("email") or None

    if not username or not password or not invite_code:
        return jsonify({"error": "username, password, and invite_code are required"}), 400
    if not _MIN_PASSWORD_LEN <= len(password) <= _MAX_PASSWORD_LEN:
        return jsonify(
            {"error": f"password must be between {_MIN_PASSWORD_LEN} and {_MAX_PASSWORD_LEN} characters"}
        ), 400

    invite = _validate_invite_code(invite_code)
    if invite is None:
        # One generic message for unknown / used / expired — a probe must not
        # be able to tell "wrong code" from "already used" (see spec/signup.md).
        return jsonify({"error": "invalid or expired invite code"}), 403

    # Username enumeration on 409 is an accepted tradeoff — signup inherently
    # reveals whether a name is free. The invite code is NOT consumed here, so
    # the visitor can retry with a different name.
    if User.query.filter_by(username=username).first() is not None:
        return jsonify({"error": "that username is taken"}), 409
    if email is not None and User.query.filter_by(email=email).first() is not None:
        return jsonify({"error": "that email is already registered"}), 409

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        email=email,
        is_demo=False,
    )
    db.session.add(user)
    db.session.flush()  # assign user.id for the invite's used_by_user_id

    # Give the new user a starter category tree (structure only, nothing
    # budgeted) so the budget view isn't empty on first load.
    create_starter_categories(user.id)

    invite.used_at = datetime.utcnow()
    invite.used_by_user_id = user.id

    access_token = create_access_token(identity=str(user.id))
    raw_refresh_token = _issue_refresh_token(user.id, commit=False)
    db.session.commit()

    response = jsonify({"access_token": access_token})
    _set_refresh_cookie(response, raw_refresh_token)
    return response, 201


@auth_bp.route("/refresh", methods=["POST"])
@require_trusted_origin
def refresh():
    record = _find_active_refresh_token(request.cookies.get("refresh_token"), lock=True)
    if record is None:
        return jsonify({"error": "invalid or expired refresh token"}), 401

    user_id = record.user_id
    _revoke_refresh_token(record, commit=False)  # rotation — old token is now dead
    new_raw_refresh_token = _issue_refresh_token(user_id, commit=False)
    db.session.commit()  # one round-trip for both writes
    access_token = create_access_token(identity=str(user_id))

    response = jsonify({"access_token": access_token})
    _set_refresh_cookie(response, new_raw_refresh_token)
    return response, 200


@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
@require_trusted_origin
def logout():
    # Idempotent: an already-revoked or missing refresh cookie is not an error —
    # the end state ("not logged in") already holds.
    record = _find_active_refresh_token(request.cookies.get("refresh_token"))
    if record is not None:
        _revoke_refresh_token(record)

    response = jsonify({"status": "logged out"})
    _clear_refresh_cookie(response)
    return response, 200
