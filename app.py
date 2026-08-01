import os
from datetime import date
from decimal import Decimal
from functools import wraps

from flask import Flask, abort, jsonify, request, session
from flask_migrate import Migrate
from werkzeug.security import check_password_hash

from models import Account, BudgetAllocation, Category, Transaction, User, db

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "balancezero.db")
)

os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)
migrate = Migrate(app, db)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            abort(401)
        return view(*args, **kwargs)

    return wrapped


def get_owned_category(category_id):
    category = db.session.get(Category, category_id)
    if category is None:
        abort(404)
    if category.user_id != session["user_id"]:
        abort(403)
    return category


@app.route("/")
def index():
    return "BalanceZero — scaffolding only, nothing built yet."


@app.route("/login", methods=["POST"])
def login():
    user = User.query.filter_by(username=request.form["username"]).first()
    if user is None or not check_password_hash(user.password_hash, request.form["password"]):
        abort(401)
    session["user_id"] = user.id
    return jsonify(logged_in_as=user.username)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify(logged_out=True)


@app.route("/dashboard")
@login_required
def dashboard():
    user = db.session.get(User, session["user_id"])
    return jsonify(username=user.username, is_demo=user.is_demo)


@app.route("/categories", methods=["POST"])
@login_required
def create_category():
    category = Category(user_id=session["user_id"], name=request.form["name"])
    db.session.add(category)
    db.session.commit()
    return jsonify(id=category.id, name=category.name), 201


@app.route("/categories/<int:category_id>/allocations", methods=["POST"])
@login_required
def set_allocation(category_id):
    category = get_owned_category(category_id)
    month = date.fromisoformat(request.form["month"])
    amount = Decimal(request.form["amount"])
    allocation = BudgetAllocation.query.filter_by(category_id=category.id, month=month).first()
    if allocation is None:
        allocation = BudgetAllocation(
            user_id=category.user_id, category_id=category.id, month=month, allocated_amount=amount
        )
        db.session.add(allocation)
    else:
        allocation.allocated_amount = amount
    db.session.commit()
    return jsonify(category_id=category.id, month=str(month), allocated_amount=str(allocation.allocated_amount))


@app.route("/budget", methods=["GET"])
@login_required
def budget_view():
    month = date.fromisoformat(request.args.get("month"))
    user_id = session["user_id"]

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

    return jsonify(month=str(month), ready_to_assign=str(ready_to_assign), categories=result)


if __name__ == "__main__":
    app.run(port=5002, debug=True)
