from datetime import date
from decimal import Decimal

from werkzeug.security import generate_password_hash

from app import app
from models import Account, BudgetAllocation, Category, Transaction, User, db

with app.app_context():
    db.drop_all()
    db.create_all()

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

    this_month = date(2026, 8, 1)
    db.session.add_all(
        [
            BudgetAllocation(user_id=demo.id, category_id=groceries.id, month=this_month, allocated_amount=Decimal("400.00")),
            BudgetAllocation(user_id=demo.id, category_id=rent.id, month=this_month, allocated_amount=Decimal("1000.00")),
        ]
    )

    db.session.add_all(
        [
            Transaction(account_id=checking.id, posted_at=date(2026, 8, 1), amount=Decimal("1500.00"), description="Paycheck"),
            Transaction(account_id=checking.id, category_id=groceries.id, posted_at=date(2026, 8, 3), amount=Decimal("-62.14"), description="Grocery store"),
            Transaction(account_id=checking.id, category_id=rent.id, posted_at=date(2026, 8, 1), amount=Decimal("-1000.00"), description="Rent"),
        ]
    )
    db.session.commit()

    # "Ready to assign" — only UNcategorized inflow (income that hasn't been claimed by a
    # category yet), minus everything ever allocated. Spending never touches this pool
    # directly — it only reduces the category's own available balance below. Money flows
    # income -> ready-to-assign -> (allocate) -> category available -> (spend) -> gone;
    # it never flows back "up" from a category to ready-to-assign.
    uncategorized_inflow = db.session.query(db.func.sum(Transaction.amount)).join(Account).filter(
        Account.user_id == demo.id, Transaction.category_id.is_(None)
    ).scalar() or Decimal("0")
    total_allocated = db.session.query(db.func.sum(BudgetAllocation.allocated_amount)).filter(
        BudgetAllocation.user_id == demo.id
    ).scalar() or Decimal("0")
    ready_to_assign = uncategorized_inflow - total_allocated

    print(f"Uncategorized inflow (income not yet assigned): {uncategorized_inflow}")
    print(f"Total allocated (all categories, all months): {total_allocated}")
    print(f"Ready to assign: {ready_to_assign}")
    print()

    # Category available balance: cumulative allocations + cumulative transactions
    # (spending is a negative amount, so it subtracts itself). Because this sums ALL
    # months to date rather than just the current one, rollover falls out for free —
    # no separate "carry the balance forward" step is needed.
    for cat in [groceries, rent]:
        allocated = db.session.query(db.func.sum(BudgetAllocation.allocated_amount)).filter(
            BudgetAllocation.category_id == cat.id
        ).scalar() or Decimal("0")
        spent = db.session.query(db.func.sum(Transaction.amount)).filter(
            Transaction.category_id == cat.id
        ).scalar() or Decimal("0")
        print(f"{cat.name}: allocated={allocated} + transactions={spent} -> available={allocated + spent}")
