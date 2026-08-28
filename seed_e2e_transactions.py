"""Additively seeds one account, one category, and one uncategorized transaction
for the e2e test user — run only by frontend/e2e/transactions.spec.ts's own
beforeAll, not by the shared global-setup, since this data would change the
"$0.00 ready to assign" the login/budget e2e test asserts on a fresh seed."""

from datetime import date
from decimal import Decimal

from app import app
from models import Account, Category, Transaction, User, db

E2E_USERNAME = "sam"

with app.app_context():
    user = User.query.filter_by(username=E2E_USERNAME).first()
    if user is None:
        raise SystemExit(f"user '{E2E_USERNAME}' not found — run seed_e2e.py first")

    if Account.query.filter_by(user_id=user.id).first() is None:
        account = Account(user_id=user.id, name="E2E Checking")
        db.session.add(account)
        db.session.flush()

        category = Category(user_id=user.id, name="Groceries")
        db.session.add(category)
        db.session.flush()

        db.session.add(
            Transaction(
                account_id=account.id,
                posted_at=date.today(),
                amount=Decimal("-42.50"),
                description="E2E Grocery Run",
            )
        )
        # A transfer row — the Transactions page badges it and the budget
        # math ignores it (changes/019).
        db.session.add(
            Transaction(
                account_id=account.id,
                posted_at=date.today(),
                amount=Decimal("-300.00"),
                description="E2E Transfer To Savings",
                transfer=True,
            )
        )
        db.session.commit()
        print("Seeded e2e account/category/transaction.")
    else:
        print("e2e account already seeded, skipping.")
