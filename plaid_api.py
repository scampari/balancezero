from datetime import date, datetime
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
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from sqlalchemy.exc import IntegrityError

from api_helpers import current_user_id, infer_category_id
from models import Account, PlaidItem, Transaction, User, db

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


@plaid_bp.route("/link-token", methods=["POST"])
@jwt_required()
def create_link_token():
    user = _load_non_demo_user()
    if user is None:
        return jsonify({"error": "the demo account cannot connect a real bank"}), 403

    link_token_args = dict(
        products=[Products("transactions")],
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
        link_token_args["redirect_uri"] = redirect_uri
    request_body = LinkTokenCreateRequest(**link_token_args)
    try:
        response = _plaid_client().link_token_create(request_body)
    except Exception:
        # Broad on purpose, scoped to just this one call: Plaid's SDK only
        # raises ApiException for HTTP-error-status responses — a true
        # outage (connection refused, DNS failure, timeout) raises a raw
        # urllib3/network exception instead, which the spec's "Plaid
        # outage" error case still expects sanitized to a 502, not a leaked
        # 500.
        return jsonify(_GENERIC_PLAID_ERROR), 502

    return jsonify({"link_token": response["link_token"]}), 200


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
    account.currency = balances["iso_currency_code"] or account.currency
    account.balance = balances["current"] or 0
    account.available_balance = balances["available"]
    db.session.flush()  # so a same-page transaction upsert can use account.id
    if is_new:
        _add_starting_balance(account, plaid_item)
    return account


def _add_starting_balance(account, plaid_item):
    """A one-time synthetic "To Be Budgeted" transaction equal to the
    account's balance at first sync, so ready_to_assign reflects money
    already in the bank — the import cutoff means transactions that predate
    the connection are never pulled, so without this the balance would
    silently vanish from the budget. Dated at the connection date. Only
    created on account creation, so re-syncing never adds a second one;
    skipped for a zero balance (nothing to reconcile)."""
    if not account.balance:
        return
    db.session.add(
        Transaction(
            account_id=account.id,
            category_id=None,
            plaid_transaction_id=None,  # synthetic, not from Plaid
            posted_at=plaid_item.import_cutoff or date.today(),
            amount=account.balance,
            description="Starting Balance",
            pending=False,
            is_income=True,
        )
    )


def _upsert_transaction(account, plaid_transaction, category_cache=None):
    """Plaid-owned fields only — never touches category_id on an *existing*
    row, so a user's categorization survives any future upsert. Plaid's
    amount sign convention is the OPPOSITE of this app's (positive = outflow
    for Plaid; positive = inflow here) — see spec/plaid-sync.md's Notes.
    Negate on every write. A brand-new row with no category is auto-filled
    from a prior same-merchant choice (infer_category_id)."""
    transaction = Transaction.query.filter_by(
        account_id=account.id, plaid_transaction_id=plaid_transaction["transaction_id"]
    ).first()
    is_new = transaction is None
    if is_new:
        transaction = Transaction(account_id=account.id, plaid_transaction_id=plaid_transaction["transaction_id"])
        db.session.add(transaction)
    transaction.amount = -Decimal(str(plaid_transaction["amount"]))
    transaction.description = plaid_transaction["name"]
    transaction.posted_at = plaid_transaction["date"]
    transaction.pending = plaid_transaction["pending"]

    if is_new and transaction.category_id is None and not transaction.is_income:
        inferred = infer_category_id(account.user_id, transaction.description, category_cache)
        if inferred is not None:
            transaction.category_id = inferred


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
}


def _within_import_window(plaid_transaction, item):
    """A fresh connection ignores the historical backfill — only transactions
    dated on/after item.import_cutoff are imported. Null cutoff (backfilled
    rows) = import everything. Applies to `added` and `modified`; `removed`
    is naturally a no-op for anything never imported."""
    if item.import_cutoff is None:
        return True
    posted = plaid_transaction["date"]
    if isinstance(posted, str):
        posted = date.fromisoformat(posted)
    return posted >= item.import_cutoff


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
            _upsert_transaction(_account_for(plaid_transaction["account_id"]), plaid_transaction, category_cache)
            counters["transactions_added"] += 1

        for plaid_transaction in response["modified"]:
            if not _should_import(plaid_transaction, item):
                continue
            _upsert_transaction(_account_for(plaid_transaction["account_id"]), plaid_transaction, category_cache)
            counters["transactions_modified"] += 1

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
