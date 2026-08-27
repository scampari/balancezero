"""Additively seeds a dedicated user ('sam-budget') with a hierarchy, a
funded yearly target, a categorized current-month transaction, and one
archived category — everything frontend/e2e/budget-management.spec.ts needs.

Uses its own user (not 'sam') so it can't perturb the "$0.00 ready to
assign" that login-and-budget.spec.ts asserts for the fresh 'sam' user,
regardless of spec run order. Run only by that spec's beforeAll."""

from datetime import date
from decimal import Decimal

from werkzeug.security import generate_password_hash

from app import app
from models import Account, BudgetAllocation, Category, CategoryTarget, Transaction, User, db

E2E_USERNAME = "sam-budget"
E2E_PASSWORD = "correct horse battery staple"
CURRENT_MONTH = date.today().replace(day=1)

with app.app_context():
    user = User.query.filter_by(username=E2E_USERNAME).first()
    if user is None:
        user = User(username=E2E_USERNAME, password_hash=generate_password_hash(E2E_PASSWORD))
        db.session.add(user)
        db.session.commit()

    if Category.query.filter_by(user_id=user.id).first() is not None:
        print("budget e2e data already seeded, skipping.")
    else:
        account = Account(user_id=user.id, name="E2E Budget Checking")
        db.session.add(account)
        db.session.flush()

        food = Category(user_id=user.id, name="Food", position=0)
        db.session.add(food)
        db.session.flush()
        groceries = Category(user_id=user.id, name="Groceries", position=0, parent_id=food.id)
        dining = Category(user_id=user.id, name="Dining Out", position=1, parent_id=food.id)
        rent = Category(user_id=user.id, name="Rent", position=1)
        stale = Category(user_id=user.id, name="Old Subscriptions", position=2, archived=True)
        db.session.add_all([groceries, dining, rent, stale])
        db.session.flush()

        db.session.add(CategoryTarget(category_id=rent.id, target_type="yearly", target_amount=Decimal("12000")))
        db.session.add(
            BudgetAllocation(
                user_id=user.id, category_id=groceries.id, month=CURRENT_MONTH, allocated_amount=Decimal("400")
            )
        )
        db.session.add(
            Transaction(
                account_id=account.id,
                category_id=groceries.id,
                posted_at=CURRENT_MONTH,
                amount=Decimal("-55.25"),
                description="E2E Budget Grocery Run",
            )
        )
        db.session.commit()
        print("Seeded budget e2e user 'sam-budget' with hierarchy, target, allocation, transaction.")
