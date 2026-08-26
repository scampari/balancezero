import plaid
from cryptography.fernet import Fernet
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from plaid.api import plaid_api as plaid_api_client
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.exceptions import ApiException

from api_helpers import current_user_id
from models import User, db

plaid_bp = Blueprint("plaid_api", __name__, url_prefix="/api/plaid")

# Plaid's own API host is fixed per environment (Sandbox/Production) and set
# via the SDK's Configuration below — never derived from client input, unlike
# SimpleFIN's user-supplied claim URL. The SSRF/redirect/size-cap defenses
# spec/simplefin-connect.md needed don't apply to this threat model — see
# spec/plaid-connect.md's Notes.
_GENERIC_PLAID_ERROR = {"error": "could not reach Plaid — please try again"}


def _plaid_client():
    configuration = plaid.Configuration(
        host=plaid.Environment.Sandbox,
        api_key={
            "clientId": current_app.config["PLAID_CLIENT_ID"],
            "secret": current_app.config["PLAID_SECRET"],
        },
    )
    return plaid_api_client.PlaidApi(plaid.ApiClient(configuration))


def _encrypt(raw_value):
    fernet = Fernet(current_app.config["PLAID_ENCRYPTION_KEY"])
    return fernet.encrypt(raw_value.encode("utf-8"))


@plaid_bp.route("/link-token", methods=["POST"])
@jwt_required()
def create_link_token():
    user = db.session.get(User, current_user_id())
    if user.is_demo:
        return jsonify({"error": "the demo account cannot connect a real bank"}), 403

    request_body = LinkTokenCreateRequest(
        products=[Products("transactions")],
        client_name="BalanceZero",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=str(user.id)),
    )
    try:
        response = _plaid_client().link_token_create(request_body)
    except ApiException:
        return jsonify(_GENERIC_PLAID_ERROR), 502

    return jsonify({"link_token": response["link_token"]}), 200


@plaid_bp.route("/connect", methods=["POST"])
@jwt_required()
def connect():
    user = db.session.get(User, current_user_id())
    if user.is_demo:
        return jsonify({"error": "the demo account cannot connect a real bank"}), 403

    data = request.get_json(silent=True) or {}
    public_token = data.get("public_token")
    if not public_token:
        return jsonify({"error": "public_token is required"}), 400

    exchange_request = ItemPublicTokenExchangeRequest(public_token=public_token)
    try:
        response = _plaid_client().item_public_token_exchange(exchange_request)
    except ApiException:
        # Never relay Plaid's raw error back to the client — same
        # sanitization discipline as the SimpleFIN-era /connect.
        return jsonify(_GENERIC_PLAID_ERROR), 502

    user.plaid_access_token_encrypted = _encrypt(response["access_token"])
    user.plaid_item_id = response["item_id"]
    db.session.commit()

    return jsonify({"status": "connected"}), 200


@plaid_bp.route("/status", methods=["GET"])
@jwt_required()
def status():
    user = db.session.get(User, current_user_id())
    return jsonify({"connected": user.plaid_access_token_encrypted is not None}), 200
