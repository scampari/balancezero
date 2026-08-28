"""Seeds a dedicated user ('sam-reports') with ~4 months of categorized
transactions and monthly income, for frontend/e2e/reports.spec.ts.

Idempotent: rebuilds this user's data every run. Run only by that spec's
beforeAll."""

from datetime import date

from werkzeug.security import generate_password_hash

from app import app
from models import Account, Category, Transaction, User, db

E2E_USERNAME = "sam-reports"
E2E_PASSWORD = "correct horse battery staple"


def _month(offset):
    today = date.today().replace(day=1)
    year = today.year + (today.month - 1 - offset) // 12
    month = (today.month - 1 - offset) % 12 + 1
    return date(year, month, 15)


with app.app_context():
    user = User.query.filter_by(username=E2E_USERNAME).first()
    if user is None:
        user = User(username=E2E_USERNAME, password_hash=generate_password_hash(E2E_PASSWORD))
        db.session.add(user)
        db.session.commit()

    for account in Account.query.filter_by(user_id=user.id).all():
        Transaction.query.filter_by(account_id=account.id).delete()
    Account.query.filter_by(user_id=user.id).delete()
    Category.query.filter_by(user_id=user.id).delete()
    db.session.commit()

    account = Account(user_id=user.id, name="Reports Checking", balance=5000)
    card = Account(user_id=user.id, name="Reports Card", type="credit", subtype="credit card", balance=-400)
    db.session.add_all([account, card])
    groceries = Category(user_id=user.id, name="Groceries")
    rent = Category(user_id=user.id, name="Rent")
    db.session.add_all([groceries, rent])
    db.session.flush()

    for offset in range(4):
        when = _month(offset)
        db.session.add_all(
            [
                Transaction(account_id=account.id, posted_at=when, amount=4000, description="Payroll", is_income=True),
                Transaction(account_id=account.id, posted_at=when, amount=-1500, description="Landlord", category_id=rent.id),
                Transaction(account_id=account.id, posted_at=when, amount=-300 - offset * 25, description="WHOLE FOODS", category_id=groceries.id),
                Transaction(account_id=card.id, posted_at=when, amount=-45, description="CORNER STORE", category_id=groceries.id),
                # A credit-card payment — a transfer, excluded from the report by default.
                Transaction(account_id=account.id, posted_at=when, amount=-200, description="CARD PAYMENT", transfer=True),
            ]
        )
    db.session.commit()
    print("Seeded e2e reports user 'sam-reports' with 4 months of transactions across 2 accounts.")
