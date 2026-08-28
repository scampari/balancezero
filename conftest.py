import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://balancezero_test:balancezero_test@localhost:55432/balancezero_test",
)
# Fixed test-only Fernet key — never used for anything but the test database.
os.environ.setdefault("PLAID_ENCRYPTION_KEY", "tD039HeVFX17-RRQiCcp3Cv4NjIjKRPkdKQhAgdW6jQ=")
# app.py requires these to exist just to import (no default there, by
# design — see plaid_api.py). Placeholder values let the app + most tests
# run without a real Plaid account; tests/test_plaid_connect.py's
# requires_plaid_sandbox skip condition checks for these exact placeholder
# strings (not mere truthiness) to tell a placeholder apart from a real
# credential — keep the two in sync if either changes.
os.environ.setdefault("PLAID_CLIENT_ID", "test-placeholder-client-id")
os.environ.setdefault("PLAID_SECRET", "test-placeholder-secret")

import pytest
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

from app import app as flask_app, db
from models import InviteCode, PlaidItem, User

TEST_USERNAME = "sam"
TEST_PASSWORD = "correct horse battery staple"


@pytest.fixture()
def client():
    flask_app.config.update(TESTING=True)
    with flask_app.app_context():
        # drop_all() before create_all(), not just after: this test DB is also
        # used by the Playwright e2e suite (see seed_e2e.py), which can leave
        # rows behind. create_all() alone doesn't clear pre-existing data in
        # tables that already exist, so a leftover e2e user can collide with
        # this suite's own test_user fixture on a unique constraint.
        db.drop_all()
        db.create_all()
        yield flask_app.test_client()
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def test_user(client):
    user = User(username=TEST_USERNAME, password_hash=generate_password_hash(TEST_PASSWORD))
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def access_token(client, test_user):
    response = client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
    return response.get_json()["access_token"]


@pytest.fixture()
def auth_headers(access_token):
    return {"Authorization": f"Bearer {access_token}"}


DEMO_USERNAME = "demo-test"
DEMO_PASSWORD = "demo-password"


@pytest.fixture()
def demo_user(client):
    user = User(username=DEMO_USERNAME, password_hash=generate_password_hash(DEMO_PASSWORD), is_demo=True)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def demo_auth_headers(client, demo_user):
    response = client.post("/api/login", json={"username": DEMO_USERNAME, "password": DEMO_PASSWORD})
    return {"Authorization": f"Bearer {response.get_json()['access_token']}"}


INVITE_CODE = "test-invite-code"


@pytest.fixture()
def invite_code(client):
    code = InviteCode(code=INVITE_CODE)
    db.session.add(code)
    db.session.commit()
    return code


@pytest.fixture()
def credit_account(client, test_user):
    """A credit-card Account for `test_user` plus its auto-style "Credit Card
    Payments" group and bound payment Category — the state _ensure_payment_category
    would produce, without a sync. Returns (account, payment_category, group)."""
    from models import Account, Category

    account = Account(
        user_id=test_user.id, name="Rewards Card", type="credit", subtype="credit card", balance=0
    )
    db.session.add(account)
    db.session.flush()
    group = Category(user_id=test_user.id, name="Credit Card Payments", position=99)
    db.session.add(group)
    db.session.flush()
    payment_category = Category(
        user_id=test_user.id,
        name="Rewards Card",
        parent_id=group.id,
        position=0,
        payment_account_id=account.id,
    )
    db.session.add(payment_category)
    db.session.commit()
    return account, payment_category, group


@pytest.fixture()
def plaid_item(client, test_user):
    """A linked institution for `test_user` with a real-Fernet-encrypted
    (but fake) access token — for tests that need "already connected" state
    without a live Plaid Sandbox call."""
    fernet = Fernet(os.environ["PLAID_ENCRYPTION_KEY"])
    item = PlaidItem(
        user_id=test_user.id,
        plaid_item_id="test-item-id",
        access_token_encrypted=fernet.encrypt(b"access-sandbox-fake"),
        institution_name="First Platypus Bank",
    )
    db.session.add(item)
    db.session.commit()
    return item
