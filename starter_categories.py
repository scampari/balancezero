"""The default category tree seeded for every new user — a structure to
work from, nothing budgeted (no allocations, no targets). See changes/017
and spec/signup.md.

A top-level entry with subcategories renders as a collapsible group total
(changes/014); one with an empty list is a plain, directly-budgetable
top-level line.
"""

from models import Category, db

STARTER_CATEGORIES = [
    ("Housing", ["Rent/Mortgage", "Utilities", "Internet & Phone"]),
    ("Food", ["Groceries", "Dining Out"]),
    ("Transportation", ["Gas", "Car Payment", "Car Insurance"]),
    # No generic "Credit Card Payment" line here — connecting a card
    # auto-creates a dedicated "Credit Card Payments" group with one
    # envelope per card (changes/021).
    ("Debt Payments", ["Loans"]),
    ("Health", ["Health Insurance", "Medical & Pharmacy"]),
    ("Personal", ["Subscriptions", "Shopping", "Personal Care"]),
    ("Entertainment", ["Streaming", "Hobbies", "Travel"]),
    ("Savings", ["Emergency Fund", "Sinking Fund"]),
    ("Miscellaneous", []),
]


def create_starter_categories(user_id):
    """Insert the starter tree for a user that has no categories yet.
    No-op if they already have some. The caller commits."""
    if Category.query.filter_by(user_id=user_id).first() is not None:
        return
    for top_position, (group_name, subs) in enumerate(STARTER_CATEGORIES):
        group = Category(user_id=user_id, name=group_name, position=top_position)
        db.session.add(group)
        db.session.flush()  # need group.id for the children's parent_id
        for sub_position, sub_name in enumerate(subs):
            db.session.add(
                Category(user_id=user_id, name=sub_name, parent_id=group.id, position=sub_position)
            )
