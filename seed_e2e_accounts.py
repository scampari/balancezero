"""Seeds a dedicated user ('sam-accounts') with one linked institution
holding a credit card (plus its "Credit Card Payments" envelope) and a
checking account — everything frontend/e2e/accounts.spec.ts needs to
exercise the "Paying this off" (debt-payoff) toggle.

Idempotent: rebuilds this user's data every run. Run only by that spec's
beforeAll."""

import os

from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

from app import app
from models import Account, Category, PlaidItem, Transaction, User, db

E2E_USERNAME = "sam-accounts"
E2E_PASSWORD = "correct horse battery staple"

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
    PlaidItem.query.filter_by(user_id=user.id).delete()
    db.session.commit()

    fernet = Fernet(os.environ["PLAID_ENCRYPTION_KEY"])
    item = PlaidItem(
        user_id=user.id,
        plaid_item_id="e2e-accounts-item",
        access_token_encrypted=fernet.encrypt(b"access-sandbox-e2e"),
        institution_name="First Platypus Bank",
    )
    db.session.add(item)
    db.session.flush()

    checking = Account(
        user_id=user.id, name="Everyday Checking", plaid_account_id="e2e-acct-chk",
        plaid_item_id=item.id, type="depository", subtype="checking", balance=2000,
    )
    card = Account(
        user_id=user.id, name="Rewards Card", plaid_account_id="e2e-acct-card",
        plaid_item_id=item.id, type="credit", subtype="credit card", balance=-800,
    )
    db.session.add_all([checking, card])
    db.session.flush()

    group = Category(user_id=user.id, name="Credit Card Payments", position=99)
    db.session.add(group)
    db.session.flush()
    db.session.add(
        Category(user_id=user.id, name="Rewards Card", parent_id=group.id, position=0,
                 payment_account_id=card.id)
    )
    db.session.commit()
    print("Seeded e2e accounts user 'sam-accounts' with 1 checking + 1 credit card.")
