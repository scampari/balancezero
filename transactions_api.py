from datetime import date

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from api_helpers import current_user_id as _current_user_id
from api_helpers import parse_month as _parse_month
from models import Account, Category, Transaction, db

transactions_bp = Blueprint("transactions_api", __name__, url_prefix="/api")


def _serialize(transaction, category_name):
    return {
        "id": transaction.id,
        "account_id": transaction.account_id,
        "category_id": transaction.category_id,
        "category_name": category_name,
        "posted_at": transaction.posted_at.isoformat(),
        "amount": str(transaction.amount),
        "description": transaction.description,
        "pending": transaction.pending,
    }


def _month_bounds(month):
    next_month = date(month.year + 1, 1, 1) if month.month == 12 else date(month.year, month.month + 1, 1)
    return month, next_month


@transactions_bp.route("/transactions", methods=["GET"])
@jwt_required()
def list_transactions():
    month_param = request.args.get("month")
    if month_param:
        month = _parse_month(month_param)
        if month is None:
            return jsonify({"error": "month must be a valid ISO date"}), 400
    else:
        month = date.today().replace(day=1)

    start, end = _month_bounds(month)
    user_id = _current_user_id()

    rows = (
        db.session.query(Transaction, Category.name)
        .join(Account, Transaction.account_id == Account.id)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .filter(Account.user_id == user_id, Transaction.posted_at >= start, Transaction.posted_at < end)
        .order_by(Transaction.posted_at.desc())
        .all()
    )

    return jsonify(
        {
            "month": month.isoformat(),
            "transactions": [_serialize(txn, category_name) for txn, category_name in rows],
        }
    ), 200


@transactions_bp.route("/transactions/<int:transaction_id>", methods=["PATCH"])
@jwt_required()
def patch_transaction(transaction_id):
    data = request.get_json(silent=True) or {}
    if "category_id" not in data:
        return jsonify({"error": "category_id is required (use null to uncategorize)"}), 400

    user_id = _current_user_id()

    transaction = (
        db.session.query(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .filter(Transaction.id == transaction_id)
        .first()
    )
    if transaction is None:
        return jsonify({"error": "transaction not found"}), 404
    if transaction.account.user_id != user_id:
        return jsonify({"error": "forbidden"}), 403

    category_id = data["category_id"]
    category_name = None
    if category_id is not None:
        category = db.session.get(Category, category_id)
        if category is None:
            return jsonify({"error": "category not found"}), 404
        if category.user_id != user_id:
            return jsonify({"error": "forbidden"}), 403
        category_name = category.name

    transaction.category_id = category_id
    db.session.commit()

    return jsonify({"id": transaction.id, "category_id": category_id, "category_name": category_name}), 200
