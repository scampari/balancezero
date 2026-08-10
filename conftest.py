import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://balancezero_test:balancezero_test@localhost:55432/balancezero_test",
)
# Fixed test-only Fernet key — never used for anything but the test database.
os.environ.setdefault("SIMPLEFIN_ENCRYPTION_KEY", "tD039HeVFX17-RRQiCcp3Cv4NjIjKRPkdKQhAgdW6jQ=")

import pytest
from werkzeug.security import generate_password_hash

from app import app as flask_app, db
from models import User

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
