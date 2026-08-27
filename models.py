from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # Optional — captured at signup when supplied, unused beyond storage for
    # now. Groundwork for a future password-reset slice so it needs no second
    # migration. Username stays the sole login identifier.
    email = db.Column(db.String(255), unique=True, nullable=True)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    # Fernet ciphertext — null for the demo user, which has no real bank connection.
    # Plaid's access_token, not a full URL (unlike the SimpleFIN-era column this replaces).
    plaid_access_token_encrypted = db.Column(db.LargeBinary, nullable=True)
    # Plaid's Item identifier — not a secret, stored plaintext alongside the encrypted token.
    plaid_item_id = db.Column(db.String(120), nullable=True)
    # /transactions/sync cursor — Item-scoped (covers every account under it),
    # not per-account; null means "never synced." See spec/plaid-sync.md's Notes.
    plaid_sync_cursor = db.Column(db.String(255), nullable=True)
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
    # Optional, two levels only (a subcategory cannot itself be a parent —
    # enforced in budget_api.py, not at the DB layer). Purely organizational:
    # a category with a parent is still independently allocatable and
    # assignable to transactions, exactly like a top-level one. No budget
    # math changes based on hierarchy.
    parent_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    # Soft-hide from the live budget view without deleting — deleting a category
    # would orphan its transactions' and allocations' history. Archived
    # categories keep every row they own; they're just excluded from
    # GET /api/budget's active list (returned separately as archived_categories)
    # and from the totals. Enforced in budget_api.py, not at the DB layer.
    archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    subcategories = db.relationship("Category", backref=db.backref("parent", remote_side=[id]))

    allocations = db.relationship("BudgetAllocation", backref="category", cascade="all, delete-orphan")
    transactions = db.relationship("Transaction", backref="category")

    __table_args__ = (db.UniqueConstraint("user_id", "name", name="uq_category_user_name"),)


class CategoryTarget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    target_type = db.Column(db.String(10), nullable=False)  # "monthly" | "yearly" | "custom"
    target_amount = db.Column(db.Numeric(12, 2), nullable=False)
    # Required for "custom", forbidden for "monthly"/"yearly" — enforced in budget_api.py.
    target_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Null = active. Setting a new target sets this on the prior active row
    # instead of deleting it — supersede, not delete (see spec/budget-api.md's
    # Notes). At most one active (superseded_at IS NULL) row per category,
    # enforced at the application layer, not a DB constraint.
    superseded_at = db.Column(db.DateTime, nullable=True)

    category = db.relationship("Category", backref=db.backref("targets", cascade="all, delete-orphan"))


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
    # Explicit "To Be Budgeted" flag (005). Mutually exclusive with category_id
    # — enforced in transactions_api.py on every write, not at the DB layer
    # (same application-level approach as CategoryTarget's one-active-row rule).
    # Feeds budget_api.py's ready_to_assign. Default false; existing rows are
    # never backfilled — a one-time per-account "Starting Balance" transaction
    # reconciles current bank balances instead (see spec/transactions.md's Notes).
    is_income = db.Column(db.Boolean, nullable=False, default=False)
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


class InviteCode(db.Model):
    """Single-use signup gate. Created only by the operator via
    mint_invite.py — there is no HTTP path that generates a code. See
    spec/signup.md."""

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Null = never expires.
    expires_at = db.Column(db.DateTime, nullable=True)
    # Null = unused. Set together on a successful signup.
    used_at = db.Column(db.DateTime, nullable=True)
    used_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)


class AuthThrottle(db.Model):
    """Fixed-window rate-limit counter for /api/login and /api/signup, keyed
    by (scope, client-IP). Not a per-account lockout (that would be a DoS
    vector) — purely a brute-force bound. See spec/signup.md's rate-limiting
    section."""

    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(20), nullable=False)  # "login" | "signup"
    key = db.Column(db.String(64), nullable=False)  # client IP
    window_start = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    count = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (db.UniqueConstraint("scope", "key", name="uq_auth_throttle_scope_key"),)
