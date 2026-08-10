"""Idempotently seeds the demo user with synthetic accounts/categories/
transactions/allocations for local interactive use. Safe to run against a
persistent dev database — does NOT drop existing data; skips seeding
entirely if the demo user already exists, so re-running after you've
started tweaking things won't wipe your changes."""

from datetime import date
from decimal import Decimal

from werkzeug.security import generate_password_hash

from app import app
from models import Account, BudgetAllocation, Category, Transaction, User, db

with app.app_context():
    db.create_all()

    if User.query.filter_by(username="demo").first() is not None:
        print("Demo user already exists, skipping seed (data left untouched).")
        raise SystemExit(0)

    demo = User(username="demo", password_hash=generate_password_hash("demo-pw"), is_demo=True)
    db.session.add(demo)
    db.session.flush()

    checking = Account(user_id=demo.id, name="Demo Checking", balance=Decimal("1500.00"))
    db.session.add(checking)
    db.session.flush()

    groceries = Category(user_id=demo.id, name="Groceries")
    rent = Category(user_id=demo.id, name="Rent")
    db.session.add_all([groceries, rent])
    db.session.flush()

    this_month = date.today().replace(day=1)
    db.session.add_all(
        [
            BudgetAllocation(user_id=demo.id, category_id=groceries.id, month=this_month, allocated_amount=Decimal("400.00")),
            BudgetAllocation(user_id=demo.id, category_id=rent.id, month=this_month, allocated_amount=Decimal("1000.00")),
        ]
    )

    db.session.add_all(
        [
            Transaction(account_id=checking.id, posted_at=this_month, amount=Decimal("1500.00"), description="Paycheck"),
            Transaction(account_id=checking.id, category_id=groceries.id, posted_at=this_month.replace(day=3), amount=Decimal("-62.14"), description="Grocery store"),
            Transaction(account_id=checking.id, category_id=rent.id, posted_at=this_month, amount=Decimal("-1000.00"), description="Rent"),
        ]
    )
    db.session.commit()

    print("Seeded demo user (username: demo, password: demo-pw) with sample accounts/categories/transactions.")
