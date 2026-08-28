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
    items_by_suffix = {}
    for suffix, name in (("a", "First Platypus Bank"), ("b", "Second Gingham Bank")):
        item = PlaidItem(
            user_id=user.id,
            plaid_item_id=f"e2e-item-{suffix}",
            access_token_encrypted=fernet.encrypt(b"access-sandbox-e2e"),
            institution_name=name,
        )
        db.session.add(item)
        db.session.flush()
        items_by_suffix[suffix] = item
        db.session.add(
            Account(
                user_id=user.id,
                name=f"{name} Checking",
                plaid_account_id=f"e2e-acct-{suffix}",
                plaid_item_id=item.id,
                type="depository",
                subtype="checking",
                balance=1000,
            )
        )
    # A second account under the first institution — a credit card, so the
    # grouped grid and the negative-liability styling both have something to
    # show (changes/018).
    db.session.add(
        Account(
            user_id=user.id,
            name="First Platypus Rewards Card",
            plaid_account_id="e2e-acct-a-card",
            plaid_item_id=items_by_suffix["a"].id,
            type="credit",
            subtype="credit card",
            balance=-250,
        )
    )
    db.session.commit()
    print("Seeded e2e Plaid user 'sam-plaid' with 2 linked institutions + 3 accounts.")
