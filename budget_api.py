from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.exc import IntegrityError

from api_helpers import current_user_id as _current_user_id
from api_helpers import parse_month as _parse_month
from models import Account, BudgetAllocation, Category, Transaction, db

budget_bp = Blueprint("budget_api", __name__, url_prefix="/api")


def _parse_amount(raw_amount):
    try:
        amount = Decimal(raw_amount)
    except (TypeError, InvalidOperation):
        return None
    if amount < 0:
        return None
    return amount


def _get_owned_category(category_id):
    """Returns (category, error_response) — error_response is None on success.
    404 for nonexistent, 403 for wrong-owner, matching the original
    get_owned_category()'s behavior (see spec/budget-api.md's Notes)."""
    category = db.session.get(Category, category_id)
    if category is None:
        return None, (jsonify({"error": "category not found"}), 404)
    if category.user_id != _current_user_id():
        return None, (jsonify({"error": "forbidden"}), 403)
    return category, None


@budget_bp.route("/categories", methods=["POST"])
@jwt_required()
def create_category():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    category = Category(user_id=_current_user_id(), name=name)
    db.session.add(category)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "a category with this name already exists"}), 409

    return jsonify({"id": category.id, "name": category.name}), 201


@budget_bp.route("/categories/<int:category_id>/allocations", methods=["POST"])
@jwt_required()
def set_allocation(category_id):
    category, error = _get_owned_category(category_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    if "month" not in data or "amount" not in data:
        return jsonify({"error": "month and amount are required"}), 400

    month = _parse_month(data["month"])
    if month is None:
        return jsonify({"error": "month must be a valid ISO date"}), 400

    amount = _parse_amount(data["amount"])
    if amount is None:
        return jsonify({"error": "amount must be a non-negative decimal"}), 400

    allocation = BudgetAllocation.query.filter_by(category_id=category.id, month=month).first()
    if allocation is None:
        allocation = BudgetAllocation(
            user_id=category.user_id, category_id=category.id, month=month, allocated_amount=amount
        )
        db.session.add(allocation)
    else:
        allocation.allocated_amount = amount
    db.session.commit()

    return jsonify(
        {"category_id": category.id, "month": month.isoformat(), "allocated_amount": str(amount)}
    ), 200


@budget_bp.route("/budget", methods=["GET"])
@jwt_required()
def get_budget():
    month_param = request.args.get("month")
    if month_param:
        month = _parse_month(month_param)
        if month is None:
            return jsonify({"error": "month must be a valid ISO date"}), 400
    else:
        month = date.today().replace(day=1)

    user_id = _current_user_id()

    uncategorized_inflow = db.session.query(db.func.sum(Transaction.amount)).join(Account).filter(
        Account.user_id == user_id, Transaction.category_id.is_(None)
    ).scalar() or Decimal("0")
    total_allocated = db.session.query(db.func.sum(BudgetAllocation.allocated_amount)).filter(
        BudgetAllocation.user_id == user_id
    ).scalar() or Decimal("0")
    ready_to_assign = uncategorized_inflow - total_allocated

    categories = Category.query.filter_by(user_id=user_id).order_by(Category.position).all()
    result = []
    for cat in categories:
        allocated_this_month = db.session.query(BudgetAllocation.allocated_amount).filter_by(
            category_id=cat.id, month=month
        ).scalar() or Decimal("0")
        allocated_total = db.session.query(db.func.sum(BudgetAllocation.allocated_amount)).filter_by(
            category_id=cat.id
        ).scalar() or Decimal("0")
        spent_total = db.session.query(db.func.sum(Transaction.amount)).filter_by(category_id=cat.id).scalar() or Decimal("0")
        result.append(
            {
                "id": cat.id,
                "name": cat.name,
                "allocated_this_month": str(allocated_this_month),
                "available": str(allocated_total + spent_total),
            }
        )

    return jsonify({"month": month.isoformat(), "ready_to_assign": str(ready_to_assign), "categories": result}), 200
