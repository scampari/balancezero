from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    # Fernet ciphertext (see lesson 0012) — null for the demo user, which has no real bank connection.
    simplefin_access_url_encrypted = db.Column(db.LargeBinary, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    accounts = db.relationship("Account", backref="user", cascade="all, delete-orphan")
    categories = db.relationship("Category", backref="user", cascade="all, delete-orphan")


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    # Null for synthetic demo-user accounts, which have no corresponding SimpleFIN account.
    simplefin_account_id = db.Column(db.String(120), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    balance = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    available_balance = db.Column(db.Numeric(12, 2), nullable=True)
    balance_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    transactions = db.relationship("Transaction", backref="account", cascade="all, delete-orphan")


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
    # (lesson 0012's rate-limited, scheduled sync) can upsert instead of duplicating.
    simplefin_transaction_id = db.Column(db.String(120), nullable=True)
    posted_at = db.Column(db.Date, nullable=False)
    # Positive = inflow, negative = outflow — matches SimpleFIN's own sign convention.
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    pending = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("account_id", "simplefin_transaction_id", name="uq_transaction_account_simplefin_id"),
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
