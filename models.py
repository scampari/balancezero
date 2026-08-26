from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    # Fernet ciphertext — null for the demo user, which has no real bank connection.
    # Plaid's access_token, not a full URL (unlike the SimpleFIN-era column this replaces).
    plaid_access_token_encrypted = db.Column(db.LargeBinary, nullable=True)
    # Plaid's Item identifier — not a secret, stored plaintext alongside the encrypted token.
    plaid_item_id = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    accounts = db.relationship("Account", backref="user", cascade="all, delete-orphan")
    categories = db.relationship("Category", backref="user", cascade="all, delete-orphan")
    refresh_tokens = db.relationship("RefreshToken", backref="user", cascade="all, delete-orphan")


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    # Null for synthetic demo-user accounts, which have no corresponding Plaid account.
    plaid_account_id = db.Column(db.String(120), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    balance = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    available_balance = db.Column(db.Numeric(12, 2), nullable=True)
    balance_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    transactions = db.relationship("Transaction", backref="account", cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint("user_id", "plaid_account_id", name="uq_account_user_plaid_id"),)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    allocations = db.relationship("BudgetAllocation", backref="category", cascade="all, delete-orphan")
    transactions = db.relationship("Transaction", backref="category")

    __table_args__ = (db.UniqueConstraint("user_id", "name", name="uq_category_user_name"),)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    # Null for synthetic demo transactions. Unique per account so a repeated sync
    # can upsert instead of duplicating.
    plaid_transaction_id = db.Column(db.String(120), nullable=True)
    posted_at = db.Column(db.Date, nullable=False)
    # Positive = inflow, negative = outflow (this app's own convention, unchanged
    # from the SimpleFIN era). CORRECTED — this comment previously claimed this
    # "matches Plaid's own sign convention," carried over from the SimpleFIN-era
    # comment without re-verifying: Plaid's is the OPPOSITE (positive = money
    # LEAVING the account, negative = money entering — confirmed against Plaid's
    # docs during plaid-sync.md's test-writing). plaid-sync.md's upsert MUST
    # negate Plaid's amount when writing to this column, or every synced
    # transaction's sign is silently backwards. See spec/plaid-sync.md's Notes.
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    pending = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("account_id", "plaid_transaction_id", name="uq_transaction_account_plaid_id"),
    )


class BudgetAllocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Denormalized alongside category_id (category already implies a user) so ownership
    # checks are a direct column comparison, not a join — see lesson 0012's IDOR lesson.
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    # Always the first of the month (e.g. 2026-08-01) — one row per category per month.
    month = db.Column(db.Date, nullable=False)
    allocated_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("category_id", "month", name="uq_allocation_category_month"),)


class RefreshToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    # SHA-256 hex digest of the raw token — never store the raw token itself,
    # same principle as password hashing (see spec/auth.md).
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime, nullable=True)
