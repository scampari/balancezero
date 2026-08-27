"""Seeds a dedicated user ('sam-plaid') with two fake linked institutions
and an account under each — everything frontend/e2e/plaid-institutions.spec.ts
needs to exercise the linked-institutions list and the Remove action,
without any real Plaid call.

Idempotent: rebuilds this user's Plaid state every run. Run only by that
spec's beforeAll."""

import os

from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

from app import app
from models import Account, PlaidItem, Transaction, User, db

E2E_USERNAME = "sam-plaid"
E2E_PASSWORD = "correct horse battery staple"

with app.app_context():
    user = User.query.filter_by(username=E2E_USERNAME).first()
    if user is None:
        user = User(username=E2E_USERNAME, password_hash=generate_password_hash(E2E_PASSWORD))
        db.session.add(user)
        db.session.commit()

    # Clear any prior run's Plaid state for this user.
    for account in Account.query.filter_by(user_id=user.id).all():
        Transaction.query.filter_by(account_id=account.id).delete()
    Account.query.filter_by(user_id=user.id).delete()
    PlaidItem.query.filter_by(user_id=user.id).delete()
    db.session.commit()

    fernet = Fernet(os.environ["PLAID_ENCRYPTION_KEY"])
    for suffix, name in (("a", "First Platypus Bank"), ("b", "Second Gingham Bank")):
        item = PlaidItem(
            user_id=user.id,
            plaid_item_id=f"e2e-item-{suffix}",
            access_token_encrypted=fernet.encrypt(b"access-sandbox-e2e"),
            institution_name=name,
        )
        db.session.add(item)
        db.session.flush()
        db.session.add(
            Account(
                user_id=user.id,
                name=f"{name} Checking",
                plaid_account_id=f"e2e-acct-{suffix}",
                plaid_item_id=item.id,
                balance=1000,
            )
        )
    db.session.commit()
    print("Seeded e2e Plaid user 'sam-plaid' with 2 linked institutions + 2 accounts.")
