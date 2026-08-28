from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from api_helpers import category_has_children as _category_has_children
from api_helpers import current_user_id as _current_user_id
from api_helpers import infer_category_id as _infer_category_id
from api_helpers import month_bounds as _month_bounds
from api_helpers import parse_month as _parse_month
from models import Account, Category, Transaction, db

_GROUP_CATEGORY_ERROR = {"error": "that category is a group — pick one of its subcategories"}

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
        "is_income": transaction.is_income,
        "transfer": transaction.transfer,
    }


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
    has_category = "category_id" in data
    has_is_income = "is_income" in data
    if not has_category and not has_is_income:
        return jsonify({"error": "category_id or is_income is required"}), 400

    # is_income:true and a real category are mutually exclusive — reject only
    # when the client asks for both in the same request. The implicit-clear
    # cases (one field set, the other left to be cleared) resolve below.
    if has_is_income and data.get("is_income") and has_category and data["category_id"] is not None:
        return jsonify({"error": "is_income and a category are mutually exclusive"}), 400

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

    category_id = transaction.category_id
    is_income = transaction.is_income
    if has_is_income:
        is_income = bool(data.get("is_income"))
        if is_income:
            category_id = None  # marking "To Be Budgeted" clears any category
    if has_category:
        category_id = data["category_id"]
        # Any categorization action is exclusive with "To Be Budgeted" — both
        # assigning a real category AND explicitly choosing "Uncategorized"
        # (category_id: null) clear is_income, unless the request itself sets
        # is_income. Without the null case, a transaction marked TBB could
        # never be moved back to plain uncategorized.
        if not has_is_income:
            is_income = False

    category_name = None
    if category_id is not None:
        category = db.session.get(Category, category_id)
        if category is None:
            return jsonify({"error": "category not found"}), 404
        if category.user_id != user_id:
            return jsonify({"error": "forbidden"}), 403
        if _category_has_children(category.id):
            return jsonify(_GROUP_CATEGORY_ERROR), 400
        category_name = category.name

    transaction.category_id = category_id
    transaction.is_income = is_income
    db.session.commit()

    return jsonify(
        {
            "id": transaction.id,
            "category_id": category_id,
            "category_name": category_name,
            "is_income": is_income,
        }
    ), 200


def _owned_transaction_or_response(transaction_id, user_id):
    """Returns (transaction, None) when the caller owns it, or
    (None, (json, status)) to return directly."""
    transaction = (
        db.session.query(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .filter(Transaction.id == transaction_id)
        .first()
    )
    if transaction is None:
        return None, (jsonify({"error": "transaction not found"}), 404)
    if transaction.account.user_id != user_id:
        return None, (jsonify({"error": "forbidden"}), 403)
    return transaction, None


@transactions_bp.route("/transactions", methods=["POST"])
@jwt_required()
def create_transaction():
    """Manually add a transaction (no Plaid link — plaid_transaction_id stays
    null). Requires one of the user's own accounts to hang it on."""
    data = request.get_json(silent=True) or {}
    account_id = data.get("account_id")
    posted_at_raw = data.get("posted_at")
    amount_raw = data.get("amount")
    description = (data.get("description") or "").strip()
    category_id = data.get("category_id")

    if account_id is None or not posted_at_raw or amount_raw is None or not description:
        return jsonify({"error": "account_id, posted_at, amount, and description are required"}), 400

    posted_at = _parse_month(posted_at_raw)  # date.fromisoformat — accepts any ISO date
    if posted_at is None:
        return jsonify({"error": "posted_at must be an ISO date (YYYY-MM-DD)"}), 400
    try:
        amount = Decimal(str(amount_raw))
    except (InvalidOperation, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    user_id = _current_user_id()
    account = db.session.get(Account, account_id)
    if account is None:
        return jsonify({"error": "account not found"}), 404
    if account.user_id != user_id:
        return jsonify({"error": "forbidden"}), 403

    category_name = None
    if category_id is not None:
        category = db.session.get(Category, category_id)
        if category is None:
            return jsonify({"error": "category not found"}), 404
        if category.user_id != user_id:
            return jsonify({"error": "forbidden"}), 403
        if _category_has_children(category.id):
            return jsonify(_GROUP_CATEGORY_ERROR), 400
        category_name = category.name
    else:
        # No category given — auto-fill from a prior same-merchant choice.
        category_id = _infer_category_id(user_id, description)
        if category_id is not None:
            category_name = db.session.get(Category, category_id).name

    transaction = Transaction(
        account_id=account_id,
        category_id=category_id,
        posted_at=posted_at,
        amount=amount,
        description=description,
        pending=False,
        is_income=False,
    )
    db.session.add(transaction)
    db.session.commit()

    return jsonify(_serialize(transaction, category_name)), 201


@transactions_bp.route("/transactions/<int:transaction_id>", methods=["DELETE"])
@jwt_required()
def delete_transaction(transaction_id):
    transaction, response = _owned_transaction_or_response(transaction_id, _current_user_id())
    if response is not None:
        return response
    db.session.delete(transaction)
    db.session.commit()
    return jsonify({"status": "deleted"}), 200
