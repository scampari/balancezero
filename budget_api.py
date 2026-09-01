from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.exc import IntegrityError

from api_helpers import current_user_id as _current_user_id
from api_helpers import month_bounds as _month_bounds
from api_helpers import parse_month as _parse_month
from models import Account, BudgetAllocation, Category, CategoryTarget, Transaction, db

budget_bp = Blueprint("budget_api", __name__, url_prefix="/api")

TARGET_TYPES = ("monthly", "yearly", "custom")


def _parse_amount(raw_amount):
    try:
        amount = Decimal(raw_amount)
    except (TypeError, InvalidOperation):
        return None
    if amount < 0:
        return None
    return amount


def _parse_positive_amount(raw_amount):
    amount = _parse_amount(raw_amount)
    if amount is None or amount == 0:
        return None
    return amount


def _parse_date(raw_date):
    try:
        return date.fromisoformat(raw_date)
    except (TypeError, ValueError):
        return None


def _months_remaining(today, through_year, through_month):
    return (through_year - today.year) * 12 + (through_month - today.month) + 1


def _target_months_remaining(target):
    """Whole calendar months from the current month through the target's
    horizon, inclusive of both ends. `monthly` has a one-month horizon."""
    if target.target_type == "monthly":
        return 1
    today = date.today()
    if target.target_type == "yearly":
        return _months_remaining(today, today.year, 12)
    return _months_remaining(today, target.target_date.year, target.target_date.month)


def _serialize_target(target):
    months = _target_months_remaining(target)
    if target.target_type == "monthly":
        monthly_target_amount = target.target_amount
    else:
        monthly_target_amount = (target.target_amount / months).quantize(Decimal("0.01"))

    return {
        "id": target.id,
        "category_id": target.category_id,
        "target_type": target.target_type,
        "target_amount": str(target.target_amount),
        "target_date": target.target_date.isoformat() if target.target_date else None,
        "monthly_target_amount": str(monthly_target_amount),
    }


def _target_budget_view(target, allocated_this_month, available):
    """The GET /api/budget per-category `target` embed: the four baseline
    fields (kept identical to _serialize_target for back-compat) plus
    progress toward the goal.

    `funded` is what's already set aside toward the target — the category's
    rolled-over envelope balance for a dated goal, or this month's assignment
    for a recurring monthly goal. `needed_this_month` is what to assign now
    to stay on pace: the shortfall spread over the months remaining.
    """
    base = _serialize_target(target)
    months = _target_months_remaining(target)
    target_amount = target.target_amount

    if target.target_type == "monthly":
        funded = allocated_this_month
        needed = max(Decimal("0"), target_amount - funded)
    else:
        funded = max(Decimal("0"), available)
        needed = max(Decimal("0"), (target_amount - funded) / months)

    progress = min(Decimal("1"), funded / target_amount) if target_amount > 0 else Decimal("0")

    return {
        "target_type": base["target_type"],
        "target_amount": base["target_amount"],
        "target_date": base["target_date"],
        "monthly_target_amount": base["monthly_target_amount"],
        "months_remaining": months,
        "funded": str(funded),
        "needed_this_month": str(needed.quantize(Decimal("0.01"))),
        "progress": str(progress.quantize(Decimal("0.0001"))),
    }


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


def _sibling_group(user_id, parent_id):
    """The user's categories that share a parent (parent_id None = top level),
    ordered as they'd appear in the budget view."""
    return (
        Category.query.filter_by(user_id=user_id, parent_id=parent_id)
        .order_by(Category.position, Category.id)
        .all()
    )


def _pack_siblings(user_id, parent_id):
    """Renumber a sibling group's positions to a gap-free 0..n-1 sequence,
    preserving current order. Called after any reparent or reorder so
    positions never drift or collide."""
    for index, sibling in enumerate(_sibling_group(user_id, parent_id)):
        sibling.position = index


@budget_bp.route("/categories", methods=["POST"])
@jwt_required()
def create_category():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    parent_id = data.get("parent_id")
    if parent_id is not None:
        parent, error = _get_owned_category(parent_id)
        if error:
            return error
        # Two levels only — a subcategory can't itself be a parent. Keeps
        # the hierarchy simple (matches "categories and subcategories",
        # not arbitrary nesting) and avoids needing cycle detection.
        if parent.parent_id is not None:
            return jsonify({"error": "a subcategory cannot itself have subcategories"}), 400

    category = Category(user_id=_current_user_id(), name=name, parent_id=parent_id)
    db.session.add(category)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "a category with this name already exists"}), 409

    return jsonify({"id": category.id, "name": category.name, "parent_id": category.parent_id}), 201


def _serialize_category(category):
    return {
        "id": category.id,
        "name": category.name,
        "parent_id": category.parent_id,
        "archived": category.archived,
        "position": category.position,
    }


@budget_bp.route("/categories/<int:category_id>", methods=["PATCH"])
@jwt_required()
def update_category(category_id):
    category, error = _get_owned_category(category_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    recognized = {"name", "parent_id", "archived", "position"}
    if not recognized & data.keys():
        return jsonify({"error": "provide at least one of name, parent_id, archived, position"}), 400

    # An auto-created credit-card payment category is managed by its card
    # binding — only reordering is allowed (changes/021).
    if category.payment_account_id is not None and (data.keys() - {"position"}):
        return jsonify({"error": "a credit-card payment category can't be renamed, moved, or archived"}), 400

    user_id = _current_user_id()
    has_children = Category.query.filter_by(parent_id=category.id).first() is not None
    old_parent_id = category.parent_id

    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        category.name = name

    if "parent_id" in data:
        new_parent_id = data["parent_id"]
        if new_parent_id is not None:
            if new_parent_id == category.id:
                return jsonify({"error": "a category cannot be its own parent"}), 400
            parent = db.session.get(Category, new_parent_id)
            if parent is None:
                return jsonify({"error": "parent not found"}), 400
            if parent.user_id != user_id:
                return jsonify({"error": "forbidden"}), 403
            if parent.parent_id is not None:
                return jsonify({"error": "a subcategory cannot itself have subcategories"}), 400
            if has_children:
                return jsonify({"error": "a category with subcategories cannot become a subcategory"}), 400
        category.parent_id = new_parent_id

    if "archived" in data:
        want_archived = bool(data["archived"])
        if want_archived and not category.archived:
            active_child = Category.query.filter_by(
                parent_id=category.id, archived=False
            ).first()
            if active_child is not None:
                return jsonify(
                    {"error": "archive or move this category's subcategories first"}
                ), 400
        if not want_archived and category.archived:
            if category.parent_id is not None:
                parent = db.session.get(Category, category.parent_id)
                if parent is not None and parent.archived:
                    return jsonify({"error": "unarchive the parent category first"}), 400
        category.archived = want_archived

    if "position" in data:
        try:
            requested_position = int(data["position"])
        except (TypeError, ValueError):
            db.session.rollback()
            return jsonify({"error": "position must be an integer"}), 400
    else:
        requested_position = None

    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "a category with this name already exists"}), 409

    reparented = "parent_id" in data and category.parent_id != old_parent_id
    if reparented:
        # Land at the end of the destination group first (so a bare reparent
        # is deterministic), and normalize the group we left.
        category.position = len(_sibling_group(user_id, category.parent_id))
        _pack_siblings(user_id, old_parent_id)

    if requested_position is not None:
        group = [c for c in _sibling_group(user_id, category.parent_id) if c.id != category.id]
        index = max(0, min(requested_position, len(group)))
        group.insert(index, category)
        for i, sibling in enumerate(group):
            sibling.position = i
    elif reparented:
        _pack_siblings(user_id, category.parent_id)

    db.session.commit()
    return jsonify(_serialize_category(category)), 200


@budget_bp.route("/categories/<int:category_id>/target", methods=["POST"])
@jwt_required()
def set_target(category_id):
    category, error = _get_owned_category(category_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}

    target_type = data.get("target_type")
    if target_type not in TARGET_TYPES:
        return jsonify({"error": "target_type must be one of monthly, yearly, custom"}), 400

    amount = _parse_positive_amount(data.get("target_amount"))
    if amount is None:
        return jsonify({"error": "target_amount must be a positive decimal"}), 400

    target_date = None
    if target_type == "custom":
        raw_date = data.get("target_date")
        if raw_date is None:
            return jsonify({"error": "target_date is required for a custom target"}), 400
        target_date = _parse_date(raw_date)
        if target_date is None:
            return jsonify({"error": "target_date must be a valid ISO date"}), 400
        current_month = date.today().replace(day=1)
        if target_date.replace(day=1) <= current_month:
            return jsonify({"error": "target_date must be after the current month"}), 400
    elif data.get("target_date") is not None:
        return jsonify({"error": "target_date is only valid for a custom target"}), 400

    previous_active = CategoryTarget.query.filter_by(category_id=category.id, superseded_at=None).first()
    if previous_active is not None:
        previous_active.superseded_at = datetime.utcnow()

    target = CategoryTarget(
        category_id=category.id, target_type=target_type, target_amount=amount, target_date=target_date
    )
    db.session.add(target)
    db.session.commit()

    return jsonify(_serialize_target(target)), 201


@budget_bp.route("/categories/<int:category_id>/target", methods=["GET"])
@jwt_required()
def get_target(category_id):
    category, error = _get_owned_category(category_id)
    if error:
        return error

    target = CategoryTarget.query.filter_by(category_id=category.id, superseded_at=None).first()
    return jsonify({"target": _serialize_target(target) if target else None}), 200


@budget_bp.route("/categories/<int:category_id>/allocations", methods=["POST"])
@jwt_required()
def set_allocation(category_id):
    category, error = _get_owned_category(category_id)
    if error:
        return error

    if Category.query.filter_by(parent_id=category.id, archived=False).first() is not None:
        return jsonify(
            {"error": "this is a group category — assign a budget to its subcategories instead"}
        ), 400

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

    start, end = _month_bounds(month)
    user_id = _current_user_id()

    # Transfers between the user's own accounts (incl. credit-card payments)
    # never count as spending or income — the money just moved (changes/019).
    # "Ready to assign" is a single global figure, the same on every month
    # (changes/026, reverting the brief month-scoped attempt in 025): all-time
    # income minus every allocation ever made, for any month. Assigning money
    # into a future month debits this pool right now, so the same dollars can
    # never look assignable in two different months. Only the per-category
    # `available` / `rollover` numbers are month-bounded (see below).
    income_total = db.session.query(db.func.sum(Transaction.amount)).join(Account).filter(
        Account.user_id == user_id,
        Transaction.is_income.is_(True),
        Transaction.transfer.is_(False),
    ).scalar() or Decimal("0")
    total_allocated = db.session.query(db.func.sum(BudgetAllocation.allocated_amount)).filter(
        BudgetAllocation.user_id == user_id,
    ).scalar() or Decimal("0")
    ready_to_assign = income_total - total_allocated

    categories = (
        Category.query.filter_by(user_id=user_id).order_by(Category.position, Category.id).all()
    )

    # A top-level category with at least one non-archived child is a *group*:
    # not spendable/allocatable itself, its columns are the sum of its
    # children (plus any of its own legacy allocation/spend, so nothing that
    # was budgeted before the split silently vanishes). See spec/budget-api.md.
    group_parent_ids = {c.parent_id for c in categories if c.parent_id is not None and not c.archived}
    child_ids_by_parent = {}
    for c in categories:
        if c.parent_id is not None and not c.archived:
            child_ids_by_parent.setdefault(c.parent_id, []).append(c.id)

    own = {}
    for cat in categories:
        allocated_this_month = db.session.query(BudgetAllocation.allocated_amount).filter_by(
            category_id=cat.id, month=month
        ).scalar() or Decimal("0")
        # Month-bounded envelope balance (changes/025): everything allocated for
        # this month or earlier, plus every signed transaction posted before the
        # month ends. Anything dated in a later month is invisible from here.
        allocated_through = db.session.query(db.func.sum(BudgetAllocation.allocated_amount)).filter(
            BudgetAllocation.category_id == cat.id,
            BudgetAllocation.month <= month,
        ).scalar() or Decimal("0")
        # A transaction the user has put in a category is budget-relevant by
        # that act, even if Plaid tagged it a transfer (changes/028): Venmo,
        # student-loan and similar payments get auto-flagged `transfer` but
        # are real spending. The flag still hides *uncategorized* transfers,
        # which never reach these `category_id == cat.id` queries anyway.
        spent_through_end = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.category_id == cat.id,
            Transaction.posted_at < end,
        ).scalar() or Decimal("0")
        spent_this_month = db.session.query(db.func.sum(Transaction.amount)).join(Account).filter(
            Transaction.category_id == cat.id,
            Account.user_id == user_id,
            Transaction.posted_at >= start,
            Transaction.posted_at < end,
        ).scalar() or Decimal("0")
        available = allocated_through + spent_through_end
        own[cat.id] = {
            "allocated_this_month": allocated_this_month,
            "spent_this_month": spent_this_month,
            "available": available,
            # What carried in from prior months — negative if the category was
            # overspent through the end of last month, positive if it had a
            # leftover balance.
            "rollover": available - allocated_this_month - spent_this_month,
        }

    # --- envelope-style credit-card budgeting (changes/021) --------------
    # Each auto-created payment category is bound to a card. Its "available"
    # is the cash set aside to pay that card down:
    #   available(P) = Σ(allocations to P)                 [already in own]
    #                + moved_in(P)   spending on the card, from a real envelope
    #                - cc_payments(P)  money paid onto the card
    #                + cc_opening(P)   the card's negative opening balance
    # The card *purchase* still counts as spend in its own spending category
    # (unchanged) — we do NOT also subtract it here. The two net out in
    # totals.available: an envelope goes down, the payment envelope goes up.
    account_by_payment_cat = {c.id: c.payment_account_id for c in categories if c.payment_account_id}
    payment_cat_ids = set(account_by_payment_cat)
    card_totals = {}  # payment_cat_id -> display extras
    if account_by_payment_cat:
        card_ids = set(account_by_payment_cat.values())
        # Sum the three components per card account in one pass each. Bounded to
        # transactions posted before the viewed month ends (changes/025) so a
        # payment envelope's `available` is the cash-to-pay-down as of that
        # month, consistent with every other category.
        def _by_card(*clauses):
            rows = (
                db.session.query(Transaction.account_id, db.func.sum(Transaction.amount))
                .filter(
                    Transaction.account_id.in_(card_ids),
                    Transaction.posted_at < end,
                    *clauses,
                )
                .group_by(Transaction.account_id)
                .all()
            )
            return {account_id: total or Decimal("0") for account_id, total in rows}

        normal_card_spend = _by_card(
            Transaction.amount < 0,
            Transaction.category_id.isnot(None),  # categorized => real spend (changes/028)
            Transaction.category_id.notin_(payment_cat_ids),
        )
        card_payments = _by_card(Transaction.transfer.is_(True), Transaction.amount > 0)
        card_opening = _by_card(
            Transaction.description == "Starting Balance",
            Transaction.plaid_transaction_id.is_(None),
        )

        def _month_by_card(*clauses):
            rows = (
                db.session.query(Transaction.account_id, db.func.sum(Transaction.amount))
                .filter(
                    Transaction.account_id.in_(card_ids),
                    Transaction.posted_at >= start,
                    Transaction.posted_at < end,
                    *clauses,
                )
                .group_by(Transaction.account_id)
                .all()
            )
            return {account_id: total or Decimal("0") for account_id, total in rows}

        month_spend = _month_by_card(Transaction.amount < 0, Transaction.transfer.is_(False))
        month_payments = _month_by_card(Transaction.transfer.is_(True), Transaction.amount > 0)
        card_balance = {
            a.id: a.balance
            for a in Account.query.filter(Account.id.in_(card_ids)).all()
        }

        for pcat_id, account_id in account_by_payment_cat.items():
            moved_in = -normal_card_spend.get(account_id, Decimal("0"))  # outflows are negative
            payments = card_payments.get(account_id, Decimal("0"))
            opening = card_opening.get(account_id, Decimal("0"))
            adj = moved_in - payments + opening
            # Fold BEFORE the group roll-up so the "Credit Card Payments"
            # group totals its children correctly with no extra code.
            own[pcat_id]["available"] += adj
            own[pcat_id]["spent_this_month"] = Decimal("0")
            # spent_this_month is forced to 0 for a payment envelope, so its
            # carry-in is just whatever available isn't this month's allocation.
            own[pcat_id]["rollover"] = own[pcat_id]["available"] - own[pcat_id]["allocated_this_month"]
            card_totals[pcat_id] = {
                "card_spending_this_month": str(-month_spend.get(account_id, Decimal("0"))),
                "card_payments_this_month": str(month_payments.get(account_id, Decimal("0"))),
                "card_balance": str(card_balance.get(account_id, Decimal("0"))),
            }

    active = []
    archived = []
    totals = {
        "budgeted": Decimal("0"),
        "spent": Decimal("0"),
        "available": Decimal("0"),
        "rollover": Decimal("0"),
    }
    for cat in categories:
        o = own[cat.id]
        is_group = cat.parent_id is None and cat.id in group_parent_ids
        is_payment = cat.id in payment_cat_ids

        if is_group:
            child_ids = child_ids_by_parent.get(cat.id, [])
            disp = {
                key: o[key] + sum(own[cid][key] for cid in child_ids)
                for key in ("allocated_this_month", "spent_this_month", "available", "rollover")
            }
            target = None  # a group can't be allocated to, so a target is meaningless
        elif is_payment:
            disp = o  # already carries the folded card adjustment
            target = None  # a payment envelope's progress is card-driven, not a target
        else:
            disp = o
            active_target = CategoryTarget.query.filter_by(category_id=cat.id, superseded_at=None).first()
            target = (
                _target_budget_view(active_target, o["allocated_this_month"], o["available"])
                if active_target is not None
                else None
            )

        entry = {
            "id": cat.id,
            "name": cat.name,
            "parent_id": cat.parent_id,
            "position": cat.position,
            "archived": cat.archived,
            "is_group": is_group,
            "is_payment_category": is_payment,
            "payment_account_id": cat.payment_account_id,
            "allocated_this_month": str(disp["allocated_this_month"]),
            "spent_this_month": str(disp["spent_this_month"]),
            "available": str(disp["available"]),
            "rollover": str(disp["rollover"]),
            "target": target,
        }
        if is_payment:
            entry.update(card_totals[cat.id])
        if cat.archived:
            archived.append(entry)
        else:
            active.append(entry)
            # Totals sum each category's OWN values — a group and its children
            # aren't double-counted. A payment envelope's "spend" is the
            # card's activity, already counted in the real spending category —
            # keep it out of totals.spent, but its available/budgeted count.
            totals["budgeted"] += o["allocated_this_month"]
            if not is_payment:
                totals["spent"] += o["spent_this_month"]
            totals["available"] += o["available"]
            totals["rollover"] += o["rollover"]

    archived.sort(key=lambda e: e["name"].lower())

    return jsonify(
        {
            "month": month.isoformat(),
            "ready_to_assign": str(ready_to_assign),
            "categories": active,
            "archived_categories": archived,
            "totals": {key: str(value) for key, value in totals.items()},
        }
    ), 200
