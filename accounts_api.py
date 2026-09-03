from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from api_helpers import current_user_id
from budget_api import convert_payment_category_to_plain
from models import Account, Category, db

accounts_bp = Blueprint("accounts_api", __name__, url_prefix="/api")


def _serialize_account(account):
    return {
        "id": account.id,
        "name": account.name,
        # Plaid's classification (changes/018) — lets the UI label an
        # account and render a liability's balance as what it is. Null for
        # demo/manual/pre-018 rows.
        "type": account.type,
        "subtype": account.subtype,
        "currency": account.currency,
        "balance": str(account.balance),
        "available_balance": str(account.available_balance)
        if account.available_balance is not None
        else None,
        "balance_date": account.balance_date.isoformat() if account.balance_date else None,
        # Our own PlaidItem row id (not a Plaid identifier) — lets the UI
        # group accounts by linked institution. Null for demo/manual
        # accounts and unlinked ones.
        "plaid_item_id": account.plaid_item_id,
        # changes/029 — "I'm paying this card down." See PATCH below.
        "debt_payoff": account.debt_payoff,
    }


@accounts_bp.route("/accounts", methods=["GET"])
@jwt_required()
def list_accounts():
    accounts = Account.query.filter_by(user_id=current_user_id()).order_by(Account.name).all()
    return jsonify({"accounts": [_serialize_account(account) for account in accounts]}), 200


@accounts_bp.route("/accounts/<int:account_id>", methods=["PATCH"])
@jwt_required()
def update_account(account_id):
    """changes/029 — set the debt-payoff flag on a credit card. Turning it
    on converts the card's auto "Credit Card Payments" envelope (if any)
    into an ordinary top-level category in the same transaction."""
    account = Account.query.filter_by(id=account_id, user_id=current_user_id()).first()
    if account is None:
        return jsonify({"error": "account not found"}), 404

    data = request.get_json(silent=True) or {}
    if not isinstance(data.get("debt_payoff"), bool):
        return jsonify({"error": "debt_payoff must be true or false"}), 400
    debt_payoff = data["debt_payoff"]

    if account.type != "credit":
        return jsonify({"error": "debt_payoff is only valid for a credit card"}), 400

    turning_on = debt_payoff and not account.debt_payoff
    account.debt_payoff = debt_payoff

    if turning_on:
        payment_category = Category.query.filter_by(
            user_id=account.user_id, payment_account_id=account.id
        ).first()
        if payment_category is not None:
            convert_payment_category_to_plain(payment_category)

    db.session.commit()
    return jsonify({"account": _serialize_account(account)}), 200
