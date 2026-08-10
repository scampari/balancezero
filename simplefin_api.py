import base64
import binascii

import requests
from cryptography.fernet import Fernet
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

from api_helpers import current_user_id
from models import User, db

simplefin_bp = Blueprint("simplefin_api", __name__, url_prefix="/api/simplefin")

CLAIM_REQUEST_TIMEOUT_SECONDS = 15


def _decode_setup_token(setup_token):
    """Returns the decoded claim URL, or None if the token is malformed or
    doesn't decode to an https:// URL (defense against a malicious token
    pointing the server at an arbitrary or non-HTTPS internal address)."""
    try:
        decoded = base64.b64decode(setup_token, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not decoded.startswith("https://"):
        return None
    return decoded


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

    try:
        response = requests.post(claim_url, timeout=CLAIM_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException:
        # Never relay SimpleFIN's raw error back to the client — see
        # spec/simplefin-connect.md's error-sanitization requirement.
        return jsonify({"error": "could not connect to SimpleFIN — the setup token may be invalid or expired"}), 502

    access_url = response.text.strip()
    user.simplefin_access_url_encrypted = _encrypt(access_url)
    db.session.commit()

    return jsonify({"status": "connected"}), 200


@simplefin_bp.route("/status", methods=["GET"])
@jwt_required()
def status():
    user = db.session.get(User, current_user_id())
    return jsonify({"connected": user.simplefin_access_url_encrypted is not None}), 200
