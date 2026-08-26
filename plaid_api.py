from decimal import Decimal

import plaid
from cryptography.fernet import Fernet
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from plaid.api import plaid_api as plaid_api_client
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from api_helpers import current_user_id
from models import Account, Transaction, User, db

plaid_bp = Blueprint("plaid_api", __name__, url_prefix="/api/plaid")

# Plaid's own API host is fixed per environment (Sandbox/Production) and set
# via the SDK's Configuration below — never derived from client input, unlike
# SimpleFIN's user-supplied claim URL. The SSRF/redirect/size-cap defenses
# spec/simplefin-connect.md needed don't apply to this threat model — see
# spec/plaid-connect.md's Notes.
_GENERIC_PLAID_ERROR = {"error": "could not reach Plaid — please try again"}

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
    guard now that three routes need it."""
    user = db.session.get(User, current_user_id())
    return None if user.is_demo else user


@plaid_bp.route("/link-token", methods=["POST"])
@jwt_required()
def create_link_token():
    user = _load_non_demo_user()
    if user is None:
        return jsonify({"error": "the demo account cannot connect a real bank"}), 403

    request_body = LinkTokenCreateRequest(
        products=[Products("transactions")],
        client_name="BalanceZero",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=str(user.id)),
    )
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

    exchange_request = ItemPublicTokenExchangeRequest(public_token=public_token)
    try:
        response = _plaid_client().item_public_token_exchange(exchange_request)
    except Exception:
        # Never relay Plaid's raw error back to the client — same
        # sanitization discipline as the SimpleFIN-era /connect. Broad
        # except for the same reason as create_link_token above.
        return jsonify(_GENERIC_PLAID_ERROR), 502

    user.plaid_access_token_encrypted = _encrypt(response["access_token"])
    user.plaid_item_id = response["item_id"]
    db.session.commit()

    return jsonify({"status": "connected"}), 200


@plaid_bp.route("/status", methods=["GET"])
@jwt_required()
def status():
    user = db.session.get(User, current_user_id())
    return jsonify({"connected": user.plaid_access_token_encrypted is not None}), 200


def _upsert_account(user, plaid_account):
    """Returns the local Account row for this Plaid account, creating it if
    new. Balances are always overwritten — SimpleFIN's-era/Plaid's data,
    never user-edited."""
    account = Account.query.filter_by(user_id=user.id, plaid_account_id=plaid_account["account_id"]).first()
    balances = plaid_account["balances"]
    if account is None:
        account = Account(user_id=user.id, plaid_account_id=plaid_account["account_id"], currency="USD")
        db.session.add(account)
    account.name = plaid_account["name"]
    account.currency = balances["iso_currency_code"] or account.currency
    account.balance = balances["current"] or 0
    account.available_balance = balances["available"]
    db.session.flush()  # so a same-page transaction upsert can use account.id
    return account


def _upsert_transaction(account, plaid_transaction):
    """SimpleFIN/Plaid-owned fields only — never touches category_id, so a
    user's categorization survives any future upsert of the same
    transaction. Plaid's amount sign convention is the OPPOSITE of this
    app's (positive = outflow for Plaid; positive = inflow here) — see
    spec/plaid-sync.md's Notes. Negate on every write."""
    transaction = Transaction.query.filter_by(
        account_id=account.id, plaid_transaction_id=plaid_transaction["transaction_id"]
    ).first()
    if transaction is None:
        transaction = Transaction(account_id=account.id, plaid_transaction_id=plaid_transaction["transaction_id"])
        db.session.add(transaction)
    transaction.amount = -Decimal(str(plaid_transaction["amount"]))
    transaction.description = plaid_transaction["name"]
    transaction.posted_at = plaid_transaction["date"]
    transaction.pending = plaid_transaction["pending"]


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


def _is_mutation_during_pagination(exception):
    """Plaid raises this specific ApiException when the Item's underlying
    data changes mid-pagination (common right after connect, while the
    historical update is still landing). Documented client behavior:
    restart the whole loop from the update's starting cursor — not a
    generic failure. The error code lives in the raw response body."""
    body = getattr(exception, "body", None)
    return body is not None and "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" in str(body)


@plaid_bp.route("/sync", methods=["POST"])
@jwt_required()
def sync():
    user = _load_non_demo_user()
    if user is None:
        return jsonify({"error": "the demo account cannot connect a real bank"}), 403

    if user.plaid_access_token_encrypted is None:
        return jsonify({"error": "not connected to Plaid"}), 409

    access_token = _decrypt(user.plaid_access_token_encrypted)

    # Where this update began — mutation-during-pagination restarts here
    # (Plaid's documented semantics), which is safe because upserts are
    # idempotent: re-fetching already-committed pages just rewrites the
    # same rows.
    update_start_cursor = user.plaid_sync_cursor
    mutation_retries = 0

    accounts_synced_ids = set()
    transactions_added = 0
    transactions_modified = 0
    transactions_removed = 0

    has_more = True
    while has_more:
        sync_kwargs = {"access_token": access_token, "count": _SYNC_PAGE_SIZE}
        if user.plaid_sync_cursor:
            sync_kwargs["cursor"] = user.plaid_sync_cursor
        try:
            response = _plaid_client().transactions_sync(TransactionsSyncRequest(**sync_kwargs))
        except Exception as exc:
            if _is_mutation_during_pagination(exc) and mutation_retries < _MUTATION_RETRY_LIMIT:
                mutation_retries += 1
                user.plaid_sync_cursor = update_start_cursor
                db.session.commit()
                accounts_synced_ids.clear()
                transactions_added = transactions_modified = transactions_removed = 0
                continue
            # Never relay Plaid's raw error back to the client — same
            # sanitization discipline as connect/link-token. Whatever pages
            # already committed (in a prior loop iteration) keep their
            # state; on a mutation error the cursor was already reset to
            # the update's start, on any other failure it stays at the
            # last committed page — either way a retried sync resumes
            # safely.
            return jsonify(_GENERIC_PLAID_ERROR), 502

        # accounts_synced counts distinct accounts — Plaid resends the full
        # account list on every page, not just accounts touched on that page.
        account_by_plaid_id = {}
        for plaid_account in response["accounts"]:
            account = _upsert_account(user, plaid_account)
            account_by_plaid_id[plaid_account["account_id"]] = account
            accounts_synced_ids.add(plaid_account["account_id"])

        def _account_for(plaid_account_id):
            if plaid_account_id not in account_by_plaid_id:
                account_by_plaid_id[plaid_account_id] = Account.query.filter_by(
                    user_id=user.id, plaid_account_id=plaid_account_id
                ).first()
            return account_by_plaid_id[plaid_account_id]

        for plaid_transaction in response["added"]:
            account = _account_for(plaid_transaction["account_id"])
            _upsert_transaction(account, plaid_transaction)
            transactions_added += 1

        for plaid_transaction in response["modified"]:
            account = _account_for(plaid_transaction["account_id"])
            _upsert_transaction(account, plaid_transaction)
            transactions_modified += 1

        for removed_entry in response["removed"]:
            account = _account_for(removed_entry["account_id"])
            if account is not None and _delete_removed_transaction(account, removed_entry):
                transactions_removed += 1

        # Per-page commit, not accumulate-then-commit-once: bounds memory on
        # a large has_more history and makes a mid-sync failure resumable
        # (the cursor only advances past pages that actually committed).
        user.plaid_sync_cursor = response["next_cursor"]
        has_more = response["has_more"]
        db.session.commit()

    return (
        jsonify(
            {
                "accounts_synced": len(accounts_synced_ids),
                "transactions_added": transactions_added,
                "transactions_modified": transactions_modified,
                "transactions_removed": transactions_removed,
            }
        ),
        200,
    )
