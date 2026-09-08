"""Seeds two users for frontend/e2e/overspend-cover.spec.ts (changes/030):

- 'sam-overspend' — Groceries overspent, Dining holding a positive balance,
  and enough unassigned income to cover from Ready to Assign.
- 'sam-overspend-clean' — every category at zero or positive, for the
  "no banner when nothing is overspent" case.

Uses its own users (not 'sam' or 'sam-budget') so it can't perturb what the
other specs assert, regardless of run order — same reasoning as
seed_e2e_budget.py's docstring.

The overspent amount and Dining's balance are arguments because the spec's
cases each state their own setup: the pre-fill case needs an overspend of
37.50 to assert the dialog offers exactly that, and the insufficient-source
case needs Dining to hold less than the shortfall. Defaults match the
40.00 / 100.00 the other cases describe.

    python3 seed_e2e_overspend.py [overspend_amount] [dining_amount]

Idempotent: rebuilds both users' budget state every run. The spec's tests
move money, so it re-seeds before each test rather than once per file.
"""

import sys
from datetime import date
from decimal import Decimal

from werkzeug.security import generate_password_hash

from app import app
from models import Account, BudgetAllocation, Category, Transaction, User, db

E2E_USERNAME = "sam-overspend"
E2E_CLEAN_USERNAME = "sam-overspend-clean"
E2E_PASSWORD = "correct horse battery staple"
CURRENT_MONTH = date.today().replace(day=1)

OVERSPEND = Decimal(sys.argv[1]) if len(sys.argv) > 1 else Decimal("40.00")
DINING = Decimal(sys.argv[2]) if len(sys.argv) > 2 else Decimal("100.00")
# Enough that Ready to Assign stays positive after Dining is funded, so the
# "cover from Ready to Assign" case has a pool to draw on.
INCOME = DINING + Decimal("100.00")


def _get_or_create_user(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, password_hash=generate_password_hash(E2E_PASSWORD))
        db.session.add(user)
        db.session.commit()
    return user


def _reset(user):
    for account in Account.query.filter_by(user_id=user.id).all():
        Transaction.query.filter_by(account_id=account.id).delete()
    BudgetAllocation.query.filter_by(user_id=user.id).delete()
    Account.query.filter_by(user_id=user.id).delete()
    Category.query.filter_by(user_id=user.id).delete()
    db.session.commit()


def _budget(user, groceries_allocation):
    """Groceries with a 40.00 outflow against it, Dining funded, and income
    on top. Whether Groceries ends up overspent is decided by how much is
    allocated to it — that's the only difference between the two users."""
    account = Account(user_id=user.id, name="E2E Overspend Checking")
    db.session.add(account)
    db.session.flush()

    groceries = Category(user_id=user.id, name="Groceries", position=0)
    dining = Category(user_id=user.id, name="Dining", position=1)
    db.session.add_all([groceries, dining])
    db.session.flush()

    db.session.add_all([
        BudgetAllocation(
            user_id=user.id, category_id=dining.id, month=CURRENT_MONTH, allocated_amount=DINING
        ),
        BudgetAllocation(
            user_id=user.id, category_id=groceries.id, month=CURRENT_MONTH,
            allocated_amount=groceries_allocation,
        ),
        Transaction(
            account_id=account.id,
            category_id=groceries.id,
            posted_at=CURRENT_MONTH,
            amount=-OVERSPEND,
            description="E2E Overspend Grocery Run",
        ),
        Transaction(
            account_id=account.id,
            category_id=None,
            posted_at=CURRENT_MONTH,
            amount=INCOME,
            description="E2E Overspend Paycheck",
            is_income=True,
        ),
    ])
    db.session.commit()


with app.app_context():
    # Nothing allocated to Groceries, so its 40.00 outflow leaves it at -40.00.
    overspent = _get_or_create_user(E2E_USERNAME)
    _reset(overspent)
    _budget(overspent, Decimal("0"))

    # Groceries funded to exactly cover its outflow — nothing overspent anywhere.
    clean = _get_or_create_user(E2E_CLEAN_USERNAME)
    _reset(clean)
    _budget(clean, OVERSPEND)

    print(
        f"Seeded '{E2E_USERNAME}' (Groceries -{OVERSPEND}, Dining +{DINING}, "
        f"ready to assign {INCOME - DINING}) and '{E2E_CLEAN_USERNAME}' (nothing overspent)."
    )
