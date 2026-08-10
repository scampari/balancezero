"""Resets the e2e test database to a known, clean state: drops and recreates
all tables, then seeds exactly one test user. Run before the Playwright suite
(see frontend/e2e/global-setup.ts) — mirrors conftest.py's per-test reset,
but once per e2e run instead of once per test."""

from werkzeug.security import generate_password_hash

from app import app
from models import User, db

E2E_USERNAME = "sam"
E2E_PASSWORD = "correct horse battery staple"

with app.app_context():
    db.drop_all()
    db.create_all()
    db.session.add(User(username=E2E_USERNAME, password_hash=generate_password_hash(E2E_PASSWORD)))
    db.session.commit()
    print(f"e2e database reset, seeded user '{E2E_USERNAME}'.")
