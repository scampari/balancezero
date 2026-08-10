import hashlib
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, jwt_required
from werkzeug.security import check_password_hash

from models import RefreshToken, User, db

REFRESH_TOKEN_TTL = timedelta(days=30)

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


def _issue_refresh_token(user_id):
    raw_token = secrets.token_urlsafe(32)
    db.session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.utcnow() + REFRESH_TOKEN_TTL,
        )
    )
    db.session.commit()
    return raw_token


def _find_active_refresh_token(raw_token):
    if not raw_token:
        return None
    record = RefreshToken.query.filter_by(token_hash=_hash_token(raw_token)).first()
    if record is None or record.revoked_at is not None or record.expires_at < datetime.utcnow():
        return None
    return record


def _revoke_refresh_token(record):
    record.revoked_at = datetime.utcnow()
    db.session.commit()


def _set_refresh_cookie(response, raw_token):
    response.set_cookie(
        "refresh_token",
        raw_token,
        httponly=True,
        secure=True,
        samesite="Strict",
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
        path="/api",
    )


def _clear_refresh_cookie(response):
    response.set_cookie(
        "refresh_token",
        "",
        httponly=True,
        secure=True,
        samesite="Strict",
        max_age=0,
        path="/api",
    )


def _same_origin_or_no_origin():
    """Lightweight CSRF guard for the two cookie-touching endpoints (refresh, logout).
    SameSite=Strict already blocks the cookie cross-site in modern browsers; this is
    defense in depth for the endpoints that read it, per spec/auth.md's Notes."""
    allowed_origin = current_app.config.get("ALLOWED_ORIGIN")
    request_origin = request.headers.get("Origin")
    if allowed_origin and request_origin and request_origin != allowed_origin:
        return False
    return True


@auth_bp.route("/login", methods=["POST"])
def login():
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


@auth_bp.route("/refresh", methods=["POST"])
def refresh():
    if not _same_origin_or_no_origin():
        return jsonify({"error": "invalid origin"}), 403

    record = _find_active_refresh_token(request.cookies.get("refresh_token"))
    if record is None:
        return jsonify({"error": "invalid or expired refresh token"}), 401

    user_id = record.user_id
    _revoke_refresh_token(record)  # rotation — old token is now dead
    new_raw_refresh_token = _issue_refresh_token(user_id)
    access_token = create_access_token(identity=str(user_id))

    response = jsonify({"access_token": access_token})
    _set_refresh_cookie(response, new_raw_refresh_token)
    return response, 200


@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    if not _same_origin_or_no_origin():
        return jsonify({"error": "invalid origin"}), 403

    # Idempotent: an already-revoked or missing refresh cookie is not an error —
    # the end state ("not logged in") already holds.
    record = _find_active_refresh_token(request.cookies.get("refresh_token"))
    if record is not None:
        _revoke_refresh_token(record)

    response = jsonify({"status": "logged out"})
    _clear_refresh_cookie(response)
    return response, 200
