from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from api_helpers import current_user_id
from models import Account

accounts_bp = Blueprint("accounts_api", __name__, url_prefix="/api")


@accounts_bp.route("/accounts", methods=["GET"])
@jwt_required()
def list_accounts():
    accounts = Account.query.filter_by(user_id=current_user_id()).order_by(Account.name).all()
    return (
        jsonify(
            {
                "accounts": [
                    {
                        "id": account.id,
                        "name": account.name,
                        "currency": account.currency,
                        "balance": str(account.balance),
                        "available_balance": str(account.available_balance)
                        if account.available_balance is not None
                        else None,
                        "balance_date": account.balance_date.isoformat() if account.balance_date else None,
                    }
                    for account in accounts
                ]
            }
        ),
        200,
    )
