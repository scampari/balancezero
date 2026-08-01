
import os
from datetime import date
from decimal import Decimal
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_migrate import Migrate
from flask_wtf import CSRFProtect
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
csrf = CSRFProtect(app)


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


@app.context_processor
def inject_current_user():
    if "user_id" in session:
        user = db.session.get(User, session["user_id"])
        return {"current_username": user.username if user else None}
    return {"current_username": None}


@app.route("/")
def index():
    return redirect(url_for("budget_view")) if "user_id" in session else redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    user = User.query.filter_by(username=request.form["username"]).first()
    if user is None or not check_password_hash(user.password_hash, request.form["password"]):
        flash("Incorrect username or password.")
        return render_template("login.html"), 401
    session["user_id"] = user.id
    return redirect(url_for("budget_view"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/categories", methods=["POST"])
@login_required
def create_category():
    db.session.add(Category(user_id=session["user_id"], name=request.form["name"]))
    db.session.commit()
    return redirect(url_for("budget_view"))


@app.route("/categories//allocations", methods=["POST"])
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
    return redirect(url_for("budget_view", month=month.isoformat()))


@app.route("/budget", methods=["GET"])
@login_required
def budget_view():
    month_str = request.args.get("month")
    month = date.fromisoformat(month_str) if month_str else date.today().replace(day=1)
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

    return render_template(
        "budget.html", month=month.isoformat(), ready_to_assign=str(ready_to_assign), categories=result
    )


if __name__ == "__main__":
    app.run(port=5002, debug=True)
