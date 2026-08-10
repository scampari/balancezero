import base64
import binascii
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

from api_helpers import current_user_id
from models import User, db

simplefin_bp = Blueprint("simplefin_api", __name__, url_prefix="/api/simplefin")

CLAIM_REQUEST_TIMEOUT_SECONDS = 15
# Real SimpleFIN access URLs are a few hundred bytes; a large cap still catches
# a malicious/compromised endpoint trying to exhaust memory via the response body.
MAX_CLAIM_RESPONSE_BYTES = 4096
# SimpleFIN Bridge's own domains — the claim URL is user-supplied (decoded from
# the setup token), so this is the actual SSRF boundary, not just the https:// check.
ALLOWED_CLAIM_HOSTS = {"bridge.simplefin.org", "beta-bridge.simplefin.org"}

_GENERIC_CONNECT_ERROR = {"error": "could not connect to SimpleFIN — the setup token may be invalid or expired"}


def _decode_setup_token(setup_token):
    """Returns the decoded claim URL, or None if the token is malformed, doesn't
    decode to an https:// URL, or isn't on a known SimpleFIN Bridge domain —
    the https-only check alone doesn't stop a token aimed at an internal host."""
    try:
        decoded = base64.b64decode(setup_token, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    parsed = urlparse(decoded)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_CLAIM_HOSTS:
        return None
    return decoded


def _looks_like_access_url(value):
    """SimpleFIN Access URLs are https://user:pass@host/path. Reject anything
    else outright rather than storing and later decrypting/using it blind —
    a malicious or corrupted claim response shouldn't be able to poison this
    field with something the sync slice would later feed to an HTTP client."""
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.username) and bool(parsed.password) and bool(parsed.hostname)


def _exchange_for_access_url(claim_url):
    """POSTs to the claim URL and returns the raw Access URL, or None on any
    failure (bad status, redirect, oversized/malformed response). Redirects are
    not followed: a compromised claim endpoint could otherwise 302 the request
    to an internal address, bypassing the domain allowlist entirely."""
    try:
        response = requests.post(
            claim_url, timeout=CLAIM_REQUEST_TIMEOUT_SECONDS, allow_redirects=False, stream=True
        )
        if response.status_code != 200:
            return None
        raw_body = response.raw.read(MAX_CLAIM_RESPONSE_BYTES + 1, decode_content=True)
        if len(raw_body) > MAX_CLAIM_RESPONSE_BYTES:
            return None
        access_url = raw_body.decode("utf-8").strip()
    except (requests.RequestException, UnicodeDecodeError):
        return None

    return access_url if _looks_like_access_url(access_url) else None


def _encrypt(raw_value):
    fernet = Fernet(current_app.config["SIMPLEFIN_ENCRYPTION_KEY"])
    return fernet.encrypt(raw_value.encode("utf-8"))


@simplefin_bp.route("/connect", methods=["POST"])
@jwt_required()
def connect():
    user = db.session.get(User, current_user_id())
    if user.is_demo:
        return jsonify({"error": "the demo account cannot connect a real bank"}), 403

    data = request.get_json(silent=True) or {}
    setup_token = data.get("setup_token")
    if not setup_token:
        return jsonify({"error": "setup_token is required"}), 400

    claim_url = _decode_setup_token(setup_token)
    if claim_url is None:
        return jsonify({"error": "setup_token is invalid"}), 400

    access_url = _exchange_for_access_url(claim_url)
    if access_url is None:
        # Never relay SimpleFIN's raw error back to the client — see
        # spec/simplefin-connect.md's error-sanitization requirement.
        return jsonify(_GENERIC_CONNECT_ERROR), 502

    user.simplefin_access_url_encrypted = _encrypt(access_url)
    db.session.commit()

    return jsonify({"status": "connected"}), 200


@simplefin_bp.route("/status", methods=["GET"])
@jwt_required()
def status():
    user = db.session.get(User, current_user_id())
    return jsonify({"connected": user.simplefin_access_url_encrypted is not None}), 200
