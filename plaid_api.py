from datetime import date, datetime, timedelta
from decimal import Decimal

import plaid
from cryptography.fernet import Fernet
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from plaid.api import plaid_api as plaid_api_client
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_update import LinkTokenCreateRequestUpdate
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from sqlalchemy.exc import IntegrityError

from api_helpers import (
    DESCRIPTION_MATCH_THRESHOLD,
    current_user_id,
    description_similarity,
    infer_category_id,
)
from models import Account, Category, PlaidItem, Transaction, User, db

plaid_bp = Blueprint("plaid_api", __name__, url_prefix="/api/plaid")

# Plaid's own API host is fixed per environment (Sandbox/Production) and set
# via the SDK's Configuration below — never derived from client input, unlike
# SimpleFIN's user-supplied claim URL. The SSRF/redirect/size-cap defenses
# spec/simplefin-connect.md needed don't apply to this threat model — see
# spec/plaid-connect.md's Notes.
_GENERIC_PLAID_ERROR = {"error": "could not reach Plaid — please try again"}
_UNLINKED_LABEL = "Linked bank"  # shown when a PlaidItem has no institution_name (backfilled rows)

_PLAID_ENVIRONMENTS = {"sandbox": plaid.Environment.Sandbox, "production": plaid.Environment.Production}

# Built once and reused, not per-request: PLAID_CLIENT_ID/SECRET/ENV are
# fixed for the life of the process (read from app.config, itself read once
# from env vars at startup), and the underlying SDK client owns its own
# connection pool — rebuilding it per request meant a fresh pool (and
# TCP/TLS handshake) on every single call for no benefit.
_cached_client = None


def _plaid_client():
    global _cached_client
    if _cached_client is None:
        plaid_env = current_app.config.get("PLAID_ENV", "sandbox")
        configuration = plaid.Configuration(
            host=_PLAID_ENVIRONMENTS[plaid_env],
            api_key={
                "clientId": current_app.config["PLAID_CLIENT_ID"],
                "secret": current_app.config["PLAID_SECRET"],
            },
        )
        _cached_client = plaid_api_client.PlaidApi(plaid.ApiClient(configuration))
    return _cached_client


def _encrypt(raw_value):
    fernet = Fernet(current_app.config["PLAID_ENCRYPTION_KEY"])
    return fernet.encrypt(raw_value.encode("utf-8"))


def _decrypt(encrypted_value):
    fernet = Fernet(current_app.config["PLAID_ENCRYPTION_KEY"])
    return fernet.decrypt(encrypted_value).decode("utf-8")


def _load_non_demo_user():
    """Returns the current user, or None if they're the demo user — callers
    return 403 on None. Centralizes the "no real bank for the demo account"
    guard now that four routes need it."""
    user = db.session.get(User, current_user_id())
    return None if user.is_demo else user


def _item_summary(item):
    """Client-facing view of one linked institution. Never includes the
    access token or the raw Plaid item id."""
    return {
        "id": item.id,
        "institution_name": item.institution_name or _UNLINKED_LABEL,
        "institution_id": item.institution_id,
        "last_synced": item.last_synced_at.isoformat() if item.last_synced_at else None,
        "account_count": Account.query.filter_by(plaid_item_id=item.id).count(),
    }


def _base_link_token_args(user):
    """The `/link/token/create` fields common to a first-time link and an
    update-mode re-open: identity, app name, locale, and the dashboard
    redirect URI when one is configured. Callers add `products` (first link)
    or `access_token` + `update` (update mode)."""
    args = dict(
        client_name="BalanceZero",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=str(user.id)),
    )
    # Only sent when configured — OAuth institutions require it, and Plaid
    # rejects a redirect_uri that isn't registered in the dashboard, so an
    # unset/misconfigured value must not be passed at all. See app.py.
    redirect_uri = current_app.config.get("PLAID_REDIRECT_URI")
    if redirect_uri:
        args["redirect_uri"] = redirect_uri
    return args


def _create_link_token_or_502(link_token_args):
    """Runs `/link/token/create` and returns a Flask response tuple —
    `({"link_token": ...}, 200)` on success, the sanitized generic error at
    `502` on any failure. The except is broad on purpose, scoped to just
    this one call: Plaid's SDK only raises ApiException for HTTP-error-status
    responses — a true outage (connection refused, DNS failure, timeout)
    raises a raw urllib3/network exception instead, which the spec's "Plaid
    outage" error case still expects sanitized to a 502, not a leaked 500."""
    try:
        response = _plaid_client().link_token_create(LinkTokenCreateRequest(**link_token_args))
    except Exception:
        return jsonify(_GENERIC_PLAID_ERROR), 502
    return jsonify({"link_token": response["link_token"]}), 200


@plaid_bp.route("/link-token", methods=["POST"])
@jwt_required()
def create_link_token():
    user = _load_non_demo_user()
    if user is None:
        return jsonify({"error": "the demo account cannot connect a real bank"}), 403

    link_token_args = _base_link_token_args(user)
    link_token_args["products"] = [Products("transactions")]
    return _create_link_token_or_502(link_token_args)


@plaid_bp.route("/items/<int:item_id>/update-link-token", methods=["POST"])
@jwt_required()
def create_update_link_token(item_id):
    """Mints a link_token in Plaid Link *update mode* with account selection,
    so the user can authorize additional accounts at a bank they've already
    linked. The Item's access_token is unchanged and no public_token comes
    back — the frontend just triggers a sync afterwards, and the new
    accounts flow in through /transactions/sync. See spec/plaid-connect.md."""
    user = _load_non_demo_user()
    if user is None:
        return jsonify({"error": "the demo account cannot connect a real bank"}), 403

    item = db.session.get(PlaidItem, item_id)
    if item is None:
        return jsonify({"error": "no such linked institution"}), 404
    # Ownership by direct column comparison — the IDOR pattern from
    # context/security-requirements.md. Must return before any Plaid call.
    if item.user_id != user.id:
        return jsonify({"error": "no such linked institution"}), 403

    link_token_args = _base_link_token_args(user)
    # Update mode: pass the existing token and ask for the account-select
    # pane; never pass `products` for this use case (Plaid rejects it).
    link_token_args["access_token"] = _decrypt(item.access_token_encrypted)
    link_token_args["update"] = LinkTokenCreateRequestUpdate(account_selection_enabled=True)
    return _create_link_token_or_502(link_token_args)


@plaid_bp.route("/connect", methods=["POST"])
@jwt_required()
def connect():
    user = _load_non_demo_user()
    if user is None:
        return jsonify({"error": "the demo account cannot connect a real bank"}), 403

    data = request.get_json(silent=True) or {}
    public_token = data.get("public_token")
    if not public_token:
        return jsonify({"error": "public_token is required"}), 400
    institution_name = data.get("institution_name")
    institution_id = data.get("institution_id")

    exchange_request = ItemPublicTokenExchangeRequest(public_token=public_token)
    try:
        response = _plaid_client().item_public_token_exchange(exchange_request)
    except Exception:
        # Never relay Plaid's raw error back to the client — same
        # sanitization discipline as the SimpleFIN-era /connect.
        return jsonify(_GENERIC_PLAID_ERROR), 502

    plaid_item_id = response["item_id"]
    encrypted = _encrypt(response["access_token"])

    # Re-linking the same institution (token repair, or a second Link run)
    # updates the existing row in place — keep its cursor and accounts.
    item = PlaidItem.query.filter_by(user_id=user.id, plaid_item_id=plaid_item_id).first()
    if item is not None:
        item.access_token_encrypted = encrypted
        if institution_name:
            item.institution_name = institution_name
        if institution_id:
            item.institution_id = institution_id
    else:
        item = PlaidItem(
            user_id=user.id,
            plaid_item_id=plaid_item_id,
            access_token_encrypted=encrypted,
            institution_name=institution_name,
            institution_id=institution_id,
            # A fresh connection imports only transactions posted from today
            # on — not the ~90 days of history Plaid's first sync returns.
            import_cutoff=date.today(),
        )
        db.session.add(item)

    try:
        db.session.commit()
    except IntegrityError:
        # plaid_item_id is globally unique — this Item belongs to another
        # BalanceZero account.
        db.session.rollback()
        return jsonify({"error": "this institution is already linked to another account"}), 409

    return jsonify({"status": "connected", "item": _item_summary(item)}), 200


@plaid_bp.route("/status", methods=["GET"])
@jwt_required()
def status():
    user = db.session.get(User, current_user_id())
    items = PlaidItem.query.filter_by(user_id=user.id).order_by(PlaidItem.id).all()
    return jsonify({"items": [_item_summary(item) for item in items]}), 200


@plaid_bp.route("/items/<int:item_id>", methods=["DELETE"])
@jwt_required()
def remove_item(item_id):
    user = _load_non_demo_user()
    if user is None:
        return jsonify({"error": "the demo account cannot connect a real bank"}), 403

    item = db.session.get(PlaidItem, item_id)
    if item is None:
        return jsonify({"error": "no such linked institution"}), 404
    # Ownership by direct column comparison — the IDOR pattern from
    # context/security-requirements.md.
    if item.user_id != user.id:
        return jsonify({"error": "no such linked institution"}), 403

    # Best-effort: tell Plaid to invalidate the token / stop billing. Local
    # cleanup must not depend on Plaid being reachable.
    try:
        _plaid_client().item_remove(ItemRemoveRequest(access_token=_decrypt(item.access_token_encrypted)))
    except Exception:
        pass

    # Accounts (and their transactions) are kept — the FK is ON DELETE SET
    # NULL, so they become inert "not linked" rows. See spec/plaid-connect.md.
    db.session.delete(item)
    db.session.commit()
    return jsonify({"status": "removed"}), 200


# Plaid `type` values whose balance is a debt, not an asset. Their
# `balances.current` comes back as a positive "amount owed"; this app's
# convention is that a balance is what you *have*, so we store it negative.
_LIABILITY_TYPES = ("credit", "loan")


def _plaid_str(value):
    """Plaid's SDK hands back enum-like objects for `type` / `subtype` whose
    `str()` is the wire value ("depository", "credit card", ...). Normalize to
    a plain lowercase string, or None when absent."""
    if value is None:
        return None
    return str(value).lower() or None


def _normalize_balance(account_type, current):
    """Store a liability's balance as a negative number. Plaid reports a
    credit-card / loan `balances.current` as a positive amount owed; flipping
    it here means it sums correctly with asset balances and doesn't inflate
    the budget's Ready-to-Assign via the synthetic Starting Balance."""
    amount = current or 0
    if account_type in _LIABILITY_TYPES:
        return -abs(amount)
    return amount


def _upsert_account(user, plaid_account, plaid_item):
    """Returns the local Account row for this Plaid account, creating it if
    new. Balances are always overwritten (Plaid-owned, never user-edited).
    plaid_item_id is set on create AND update, so a backfilled or re-linked
    account gets re-attached to its institution. A brand-new account also
    gets a one-time "Starting Balance" transaction (see _add_starting_balance)."""
    account = Account.query.filter_by(user_id=user.id, plaid_account_id=plaid_account["account_id"]).first()
    balances = plaid_account["balances"]
    is_new = account is None
    if is_new:
        account = Account(user_id=user.id, plaid_account_id=plaid_account["account_id"], currency="USD")
        db.session.add(account)
    account.plaid_item_id = plaid_item.id
    account.name = plaid_account["name"]
    account.type = _plaid_str(plaid_account.get("type"))
    account.subtype = _plaid_str(plaid_account.get("subtype"))
    account.currency = balances["iso_currency_code"] or account.currency
    account.balance = _normalize_balance(account.type, balances["current"])
    account.available_balance = balances["available"]
    db.session.flush()  # so a same-page transaction upsert can use account.id
    if is_new:
        _add_starting_balance(account, plaid_item)
    if account.type == "credit":
        _ensure_payment_category(user, account)
    return account


# The dedicated top-level group that holds one payment envelope per card
# (changes/021). Kept distinct from the starter tree's "Debt Payments".
_PAYMENTS_GROUP_NAME = "Credit Card Payments"


def _find_or_create_payments_group(user):
    group = Category.query.filter_by(
        user_id=user.id, name=_PAYMENTS_GROUP_NAME, parent_id=None
    ).first()
    if group is not None:
        return group
    position = db.session.query(db.func.coalesce(db.func.max(Category.position), -1)).filter(
        Category.user_id == user.id, Category.parent_id.is_(None)
    ).scalar()
    group = Category(user_id=user.id, name=_PAYMENTS_GROUP_NAME, parent_id=None, position=position + 1)
    db.session.add(group)
    try:
        db.session.flush()
    except IntegrityError:
        # Raced another sync of the same user — reuse the row it created.
        db.session.rollback()
        group = Category.query.filter_by(
            user_id=user.id, name=_PAYMENTS_GROUP_NAME, parent_id=None
        ).first()
    return group


def _ensure_payment_category(user, account):
    """Idempotently bind a "Credit Card Payments" envelope to a credit-card
    account. Called from _upsert_account for every credit account on every
    sync, so an already-synced card gets its category on the next sync with
    no backfill migration. The unique constraint on
    Category.payment_account_id makes a concurrent double-create an
    IntegrityError we swallow."""
    existing = Category.query.filter_by(user_id=user.id, payment_account_id=account.id).first()
    if existing is not None:
        return existing

    group = _find_or_create_payments_group(user)
    child_position = db.session.query(db.func.coalesce(db.func.max(Category.position), -1)).filter(
        Category.user_id == user.id, Category.parent_id == group.id
    ).scalar()
    category = Category(
        user_id=user.id,
        name=_payment_category_name(user, account),
        parent_id=group.id,
        position=child_position + 1,
        payment_account_id=account.id,
    )
    db.session.add(category)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return Category.query.filter_by(user_id=user.id, payment_account_id=account.id).first()
    return category


def _payment_category_name(user, account):
    """The card's own name, unless a category already owns it — then suffix
    to dodge the (user_id, name) unique constraint."""
    base = account.name or "Credit Card"
    name = base
    suffix = 2
    while Category.query.filter_by(user_id=user.id, name=name).first() is not None:
        name = f"{base} ({suffix})"
        suffix += 1
    return name


def _add_starting_balance(account, plaid_item):
    """A one-time synthetic "To Be Budgeted" transaction equal to the
    account's balance at first sync, so ready_to_assign reflects money
    already in the bank — the import cutoff means transactions that predate
    the connection are never pulled, so without this the balance would
    silently vanish from the budget. Dated at the connection date. Only
    created on account creation, so re-syncing never adds a second one;
    skipped for a zero balance (nothing to reconcile).

    For a liability account (credit card / loan) the balance is stored
    negative, and the opening entry is *not* income — it's the debt you're
    carrying into the budget, not money to assign. For a depository account
    it's the positive "To Be Budgeted" inflow as before."""
    if not account.balance:
        return
    is_liability = account.type in _LIABILITY_TYPES
    db.session.add(
        Transaction(
            account_id=account.id,
            category_id=None,
            plaid_transaction_id=None,  # synthetic, not from Plaid
            posted_at=_import_cutoff(plaid_item),
            amount=account.balance,
            description="Starting Balance",
            pending=False,
            is_income=not is_liability,
        )
    )


# A `transfer` is money that moved between the user's own accounts — not
# spent, not earned — so budget math ignores it (`spec/budget-api.md`).
# We read Plaid's `personal_finance_category`:
#   - TRANSFER_IN / TRANSFER_OUT  → a transfer, EXCEPT peer-to-peer
#     (`*_P2P`: Venmo, Zelle, PayPal, Cash App), which really does leave the
#     budget to another person.
#   - LOAN_PAYMENTS → a transfer only for a credit-card payment
#     (`LOAN_PAYMENTS_CREDIT_CARD_PAYMENT`). A student / auto / mortgage /
#     personal loan payment is a real expense (changes/028).
_TRANSFER_PRIMARY_CATEGORIES = ("TRANSFER_IN", "TRANSFER_OUT")


def _is_transfer(plaid_transaction):
    pfc = plaid_transaction.get("personal_finance_category") or {}
    primary = pfc.get("primary")
    detail = pfc.get("detail") or ""
    if primary in _TRANSFER_PRIMARY_CATEGORIES:
        return not detail.endswith("_P2P")
    if primary == "LOAN_PAYMENTS":
        return detail == "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"
    return False


def _plaid_posted_date(plaid_transaction):
    """Plaid's SDK returns `date` as a native `datetime.date`; raw JSON and
    test fixtures use an ISO string. Normalize to `date`."""
    posted = plaid_transaction["date"]
    return date.fromisoformat(posted) if isinstance(posted, str) else posted


# spec/plaid-sync.md § Manual-transaction adoption — how far a hand-entered
# row's date may sit from the bank's posted date and still be the same
# transaction.
_MANUAL_MATCH_WINDOW = timedelta(days=7)


def _adopt_manual_transaction(account, plaid_transaction):
    """spec/plaid-sync.md § Manual-transaction adoption. Find the row the
    user typed in by hand before this transaction posted — same account, no
    `plaid_transaction_id` yet, exact amount (this app's sign), posted date
    within a week, and a strict (`DESCRIPTION_MATCH_THRESHOLD`) description
    match. The synthetic "Starting Balance" row is never a candidate. When
    several qualify, the nearest date wins (then the strongest description
    match, then the lowest id). Returns the row to adopt, or None."""
    posted = _plaid_posted_date(plaid_transaction)
    amount = -Decimal(str(plaid_transaction["amount"]))

    candidates = (
        Transaction.query.filter_by(account_id=account.id, plaid_transaction_id=None)
        .filter(Transaction.amount == amount, Transaction.description != "Starting Balance")
        .all()
    )

    scored = []
    for row in candidates:
        distance = abs((row.posted_at - posted).days)
        if distance > _MANUAL_MATCH_WINDOW.days:
            continue
        similarity = description_similarity(row.description, plaid_transaction["name"])
        if similarity < DESCRIPTION_MATCH_THRESHOLD:
            continue
        # id is unique, so the first three keys already order every pair —
        # nearest date, then strongest match (negated for ascending sort).
        scored.append((distance, -similarity, row.id, row))

    return min(scored)[-1] if scored else None


def _upsert_transaction(account, plaid_transaction, category_cache=None):
    """Plaid-owned fields only — never touches category_id on an *existing*
    row, so a user's categorization survives any future upsert. Plaid's
    amount sign convention is the OPPOSITE of this app's (positive = outflow
    for Plaid; positive = inflow here) — see spec/plaid-sync.md's Notes.
    Negate on every write. A brand-new row with no category is auto-filled
    from a prior same-merchant choice (infer_category_id).

    A first-time incoming transaction first tries to *adopt* a matching
    hand-entered row instead of inserting a duplicate (see
    _adopt_manual_transaction). Returns "linked" when it adopted one,
    otherwise None."""
    transaction = Transaction.query.filter_by(
        account_id=account.id, plaid_transaction_id=plaid_transaction["transaction_id"]
    ).first()
    is_new = transaction is None
    adopted = False
    if is_new:
        transaction = _adopt_manual_transaction(account, plaid_transaction)
        if transaction is not None:
            adopted = True
            transaction.plaid_transaction_id = plaid_transaction["transaction_id"]
        else:
            transaction = Transaction(
                account_id=account.id, plaid_transaction_id=plaid_transaction["transaction_id"]
            )
            db.session.add(transaction)
    transaction.amount = -Decimal(str(plaid_transaction["amount"]))
    transaction.description = plaid_transaction["name"]
    transaction.posted_at = plaid_transaction["date"]
    transaction.pending = plaid_transaction["pending"]
    transaction.transfer = _is_transfer(plaid_transaction)

    # An adopted row already carries the user's own category / is_income
    # choice — leave it. Only a genuinely new row gets auto-categorized.
    if is_new and not adopted and transaction.category_id is None and not transaction.is_income:
        inferred = infer_category_id(account.user_id, transaction.description, category_cache)
        if inferred is not None:
            transaction.category_id = inferred

    return "linked" if adopted else None


def _delete_removed_transaction(account, removed_entry):
    transaction = Transaction.query.filter_by(
        account_id=account.id, plaid_transaction_id=removed_entry["transaction_id"]
    ).first()
    if transaction is not None:
        db.session.delete(transaction)
        return True
    return False


# Plaid's documented mitigation for mutation-during-pagination: fewer,
# larger pages (default 100, max 500) make the pagination window shorter.
_SYNC_PAGE_SIZE = 500
# Plaid's documented handling for this error is to restart the whole
# pagination loop from the update's starting cursor — bounded so a
# pathologically busy Item can't loop forever.
_MUTATION_RETRY_LIMIT = 3

_EMPTY_COUNTERS = {
    "accounts_synced": 0,
    "transactions_added": 0,
    "transactions_modified": 0,
    "transactions_removed": 0,
    # changes/022 — an incoming transaction merged into a pre-existing manual
    # row instead of inserted as a new one (see _adopt_manual_transaction).
    # Lives alongside the others so the per-item result, totals, and the
    # mutation-during-pagination reset all carry it for free.
    "transactions_linked": 0,
}


def _import_cutoff(item):
    """The earliest transaction date a sync will import for this item.
    `import_cutoff` is set to the connect date on every new link; if it's
    NULL — a row created before changes/011 added the column, or otherwise
    missed — fall back to the item's own creation date rather than pulling
    Plaid's entire ~90-day history window."""
    return item.import_cutoff or item.created_at.date()


def _within_import_window(plaid_transaction, item):
    """A fresh connection ignores Plaid's historical backfill — only
    transactions dated on/after the item's import cutoff are imported.
    Applies to `added` and `modified`; `removed` is naturally a no-op for
    anything never imported."""
    return _plaid_posted_date(plaid_transaction) >= _import_cutoff(item)


def _should_import(plaid_transaction, item):
    """Gate for `added` / `modified` entries. Skips a transaction while
    Plaid still marks it `pending` — it's pulled in only once it settles
    (arrives again as non-pending, either as a `modified` on the same id or
    a fresh `added` linked by `pending_transaction_id`). Also enforces the
    fresh-connection import cutoff. See spec/plaid-sync.md."""
    return not plaid_transaction["pending"] and _within_import_window(plaid_transaction, item)


def _is_mutation_during_pagination(exception):
    """Plaid raises this specific ApiException when the Item's underlying
    data changes mid-pagination (common right after connect, while the
    historical update is still landing). Documented client behavior:
    restart the whole loop from the update's starting cursor — not a
    generic failure. The error code lives in the raw response body."""
    body = getattr(exception, "body", None)
    return body is not None and "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" in str(body)


def _sync_one_item(user, item):
    """Runs the full paginated /transactions/sync loop for one linked
    institution against its own token + cursor. Commits per page (so a
    mid-sync failure is resumable) and sets last_synced_at on success.
    Raises on an unrecoverable Plaid error — the caller records that item
    as failed and moves on to the next."""
    access_token = _decrypt(item.access_token_encrypted)

    # Where this update began — mutation-during-pagination restarts here
    # (Plaid's documented semantics), safe because upserts are idempotent.
    update_start_cursor = item.sync_cursor
    mutation_retries = 0

    accounts_synced_ids = set()
    counters = dict(_EMPTY_COUNTERS)
    # description -> category_id, reused across this item's pages so each
    # distinct merchant is looked up once (see infer_category_id).
    category_cache = {}

    has_more = True
    while has_more:
        sync_kwargs = {"access_token": access_token, "count": _SYNC_PAGE_SIZE}
        if item.sync_cursor:
            sync_kwargs["cursor"] = item.sync_cursor
        try:
            response = _plaid_client().transactions_sync(TransactionsSyncRequest(**sync_kwargs))
        except Exception as exc:
            if _is_mutation_during_pagination(exc) and mutation_retries < _MUTATION_RETRY_LIMIT:
                mutation_retries += 1
                item.sync_cursor = update_start_cursor
                db.session.commit()
                accounts_synced_ids.clear()
                counters = dict(_EMPTY_COUNTERS)
                continue
            raise

        account_by_plaid_id = {}
        for plaid_account in response["accounts"]:
            account = _upsert_account(user, plaid_account, item)
            account_by_plaid_id[plaid_account["account_id"]] = account
            accounts_synced_ids.add(plaid_account["account_id"])

        def _account_for(plaid_account_id):
            if plaid_account_id not in account_by_plaid_id:
                account_by_plaid_id[plaid_account_id] = Account.query.filter_by(
                    user_id=user.id, plaid_account_id=plaid_account_id
                ).first()
            return account_by_plaid_id[plaid_account_id]

        for plaid_transaction in response["added"]:
            if not _should_import(plaid_transaction, item):
                continue
            outcome = _upsert_transaction(
                _account_for(plaid_transaction["account_id"]), plaid_transaction, category_cache
            )
            counters["transactions_linked" if outcome == "linked" else "transactions_added"] += 1

        for plaid_transaction in response["modified"]:
            if not _should_import(plaid_transaction, item):
                continue
            outcome = _upsert_transaction(
                _account_for(plaid_transaction["account_id"]), plaid_transaction, category_cache
            )
            counters["transactions_linked" if outcome == "linked" else "transactions_modified"] += 1

        for removed_entry in response["removed"]:
            account = _account_for(removed_entry["account_id"])
            if account is not None and _delete_removed_transaction(account, removed_entry):
                counters["transactions_removed"] += 1

        item.sync_cursor = response["next_cursor"]
        has_more = response["has_more"]
        db.session.commit()

    counters["accounts_synced"] = len(accounts_synced_ids)
    item.last_synced_at = datetime.utcnow()
    db.session.commit()
    return counters


@plaid_bp.route("/sync", methods=["POST"])
@jwt_required()
def sync():
    user = _load_non_demo_user()
    if user is None:
        return jsonify({"error": "the demo account cannot connect a real bank"}), 403

    items = PlaidItem.query.filter_by(user_id=user.id).order_by(PlaidItem.id).all()
    if not items:
        return jsonify({"error": "not connected to Plaid"}), 409

    results = []
    totals = dict(_EMPTY_COUNTERS)
    any_ok = False

    for item in items:
        label = item.institution_name or _UNLINKED_LABEL
        try:
            counters = _sync_one_item(user, item)
        except Exception:
            # One institution's outage must not abort the others. Whatever
            # pages already committed for this item keep their state; its
            # cursor is where the last committed page left off, so a
            # retried sync resumes safely.
            db.session.rollback()
            results.append({"id": item.id, "institution_name": label, "status": "error",
                            "error": _GENERIC_PLAID_ERROR["error"], **_EMPTY_COUNTERS})
            continue

        any_ok = True
        results.append({"id": item.id, "institution_name": label, "status": "ok", **counters})
        for key in totals:
            totals[key] += counters[key]

    body = {
        "items": results,
        "totals": totals,
        "ok": all(result["status"] == "ok" for result in results),
    }
    # 200 as long as at least one institution synced; 502 only if every one
    # failed (nothing was accomplished — single-error UX).
    return jsonify(body), (200 if any_ok else 502)
