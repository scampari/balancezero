"""Integration tests for spec/plaid-sync.md (multi-institution, changes/008).

Real Sandbox calls for the connect + first-sync happy paths, same
mock-boundary reasoning as tests/test_plaid_connect.py. The `modified` /
`removed` / partial-failure / all-fail scenarios mock the SDK's
`transactions_sync` (per context/testing.md's "no reliably repeatable safe
test environment" fallback) while keeping connection + DB state real.

The sign convention is load-bearing: Plaid positive = outflow, this app
positive = inflow — the upsert must negate on every write.
"""

import os
import time
from decimal import Decimal

import plaid
import pytest
from cryptography.fernet import Fernet
from models import Account, PlaidItem, Transaction, db
from plaid.api import plaid_api
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.sandbox_public_token_create_request_options import SandboxPublicTokenCreateRequestOptions

SANDBOX_INSTITUTION_ID = "ins_109508"

_PLACEHOLDER_PLAID_CLIENT_ID = "test-placeholder-client-id"
_PLACEHOLDER_PLAID_SECRET = "test-placeholder-secret"
_HAS_PLAID_SANDBOX_CREDENTIALS = (
    os.environ.get("PLAID_CLIENT_ID") not in (None, _PLACEHOLDER_PLAID_CLIENT_ID)
    and os.environ.get("PLAID_SECRET") not in (None, _PLACEHOLDER_PLAID_SECRET)
)

requires_plaid_sandbox = pytest.mark.skipif(
    not _HAS_PLAID_SANDBOX_CREDENTIALS,
    reason="requires real PLAID_CLIENT_ID/PLAID_SECRET Sandbox credentials, not present in this environment",
)

_DYNAMIC_USER_OPTIONS = SandboxPublicTokenCreateRequestOptions(
    override_username="user_transactions_dynamic", override_password="pass_good"
)

_SANDBOX_READY_TIMEOUT_SECONDS = 30
_SANDBOX_READY_POLL_INTERVAL_SECONDS = 3


def _plaid_sandbox_client():
    configuration = plaid.Configuration(
        host=plaid.Environment.Sandbox,
        api_key={"clientId": os.environ["PLAID_CLIENT_ID"], "secret": os.environ["PLAID_SECRET"]},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def _connect_with_dynamic_test_data(client, auth_headers):
    request = SandboxPublicTokenCreateRequest(
        institution_id=SANDBOX_INSTITUTION_ID,
        initial_products=[Products("transactions")],
        options=_DYNAMIC_USER_OPTIONS,
    )
    public_token = _plaid_sandbox_client().sandbox_public_token_create(request)["public_token"]
    resp = client.post("/api/plaid/connect", json={"public_token": public_token}, headers=auth_headers)
    assert resp.status_code == 200, "test setup failed: real /connect call did not succeed"


def _seed_item(user, plaid_item_id="seed-item", cursor=None, name="Seed Bank", import_cutoff=None):
    """A PlaidItem with a real-Fernet-encrypted fake token — for offline
    tests that mock transactions_sync."""
    fernet = Fernet(os.environ["PLAID_ENCRYPTION_KEY"])
    item = PlaidItem(
        user_id=user.id,
        plaid_item_id=plaid_item_id,
        access_token_encrypted=fernet.encrypt(b"access-sandbox-fake"),
        sync_cursor=cursor,
        institution_name=name,
        import_cutoff=import_cutoff,
    )
    db.session.add(item)
    db.session.commit()
    return item


def _sync_until_data_present(client, auth_headers):
    deadline = time.monotonic() + _SANDBOX_READY_TIMEOUT_SECONDS
    response = None
    while time.monotonic() < deadline:
        response = client.post("/api/plaid/sync", headers=auth_headers)
        if response.status_code != 200:
            return response
        if response.get_json()["totals"]["transactions_added"] > 0:
            return response
        time.sleep(_SANDBOX_READY_POLL_INTERVAL_SECONDS)
    return response


def _mock_sync_response(added=None, modified=None, removed=None, has_more=False, next_cursor="mock-cursor"):
    return {
        "added": added or [],
        "modified": modified or [],
        "removed": removed or [],
        "accounts": [],
        "has_more": has_more,
        "next_cursor": next_cursor,
        "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE",
        "request_id": "mock-request-id",
    }


def _patch_client(monkeypatch, stub):
    import plaid_api as plaid_api_module

    monkeypatch.setattr(plaid_api_module, "_plaid_client", lambda: stub)


# ---------------------------------------------------------------------------
# POST /api/plaid/sync — guards
# ---------------------------------------------------------------------------


def test_sync_without_token_returns_401(client, test_user):
    assert client.post("/api/plaid/sync").status_code == 401


def test_sync_as_demo_user_returns_403(client, demo_auth_headers):
    assert client.post("/api/plaid/sync", headers=demo_auth_headers).status_code == 403


def test_sync_with_no_linked_institutions_returns_409(client, test_user, auth_headers):
    assert client.post("/api/plaid/sync", headers=auth_headers).status_code == 409


# ---------------------------------------------------------------------------
# POST /api/plaid/sync — multi-item behavior (offline, mocked SDK)
# ---------------------------------------------------------------------------


def test_sync_loops_every_item_and_totals_are_the_sum(client, test_user, auth_headers, monkeypatch):
    # Arrange — two linked institutions, each with one account and one
    # incoming transaction on the mocked page.
    for suffix in ("a", "b"):
        item = _seed_item(test_user, f"item-{suffix}", name=f"Bank {suffix.upper()}")
        db.session.add(
            Account(user_id=test_user.id, name=f"Acct {suffix}", plaid_account_id=f"acc-{suffix}", plaid_item_id=item.id)
        )
    db.session.commit()

    class _OneAddPerItem:
        def __init__(self):
            self.calls = 0

        def transactions_sync(self, *_a, **_k):
            self.calls += 1
            suffix = "a" if self.calls == 1 else "b"
            return _mock_sync_response(
                added=[{"transaction_id": f"t-{suffix}", "account_id": f"acc-{suffix}", "amount": 1.0,
                        "date": "2026-08-01", "name": "X", "pending": False}]
            )

    _patch_client(monkeypatch, _OneAddPerItem())

    # Act
    response = client.post("/api/plaid/sync", headers=auth_headers)

    # Assert — one result per item, totals summed across both
    assert response.status_code == 200
    body = response.get_json()
    assert len(body["items"]) == 2
    assert body["ok"] is True
    assert body["totals"]["transactions_added"] == 2


def test_sync_one_item_failing_does_not_abort_the_others(client, test_user, auth_headers, monkeypatch):
    # Arrange
    _seed_item(test_user, "item-a", name="Bank A")
    _seed_item(test_user, "item-b", name="Bank B")

    class _FirstCallFails:
        def __init__(self):
            self.calls = 0

        def transactions_sync(self, *_a, **_k):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("simulated outage for the first item")
            return _mock_sync_response()

    _patch_client(monkeypatch, _FirstCallFails())

    # Act
    response = client.post("/api/plaid/sync", headers=auth_headers)

    # Assert — 200 (something synced), ok=False, one error + one ok
    assert response.status_code == 200
    body = response.get_json()
    statuses = sorted(item["status"] for item in body["items"])
    assert statuses == ["error", "ok"]
    assert body["ok"] is False
    errored = next(item for item in body["items"] if item["status"] == "error")
    assert "error" in errored


def test_sync_all_items_failing_returns_502(client, test_user, auth_headers, monkeypatch):
    _seed_item(test_user, "item-a")
    _seed_item(test_user, "item-b")

    class _AlwaysFails:
        def transactions_sync(self, *_a, **_k):
            raise ConnectionError("everything is down")

    _patch_client(monkeypatch, _AlwaysFails())

    response = client.post("/api/plaid/sync", headers=auth_headers)
    assert response.status_code == 502
    assert response.get_json()["ok"] is False


def test_sync_sets_last_synced_at_on_success(client, test_user, auth_headers, monkeypatch):
    item = _seed_item(test_user, "item-a")
    assert item.last_synced_at is None

    class _EmptyPage:
        def transactions_sync(self, *_a, **_k):
            return _mock_sync_response()

    _patch_client(monkeypatch, _EmptyPage())

    assert client.post("/api/plaid/sync", headers=auth_headers).status_code == 200
    db.session.refresh(item)
    assert item.last_synced_at is not None


def test_sync_modified_upsert_negates_amount_and_keeps_category(client, test_user, auth_headers, monkeypatch):
    # Arrange — an item, an account under it, a categorized transaction
    item = _seed_item(test_user, "item-a")
    account = Account(user_id=test_user.id, name="Checking", plaid_account_id="acc-1", plaid_item_id=item.id)
    db.session.add(account)
    db.session.flush()
    category = client.post("/api/categories", json={"name": "Groceries"}, headers=auth_headers).get_json()
    txn = Transaction(
        account_id=account.id,
        plaid_transaction_id="txn-1",
        posted_at="2026-08-01",
        amount=-10,
        description="OLD",
        category_id=category["id"],
    )
    db.session.add(txn)
    db.session.commit()
    txn_id = txn.id

    class _Modified:
        def transactions_sync(self, *_a, **_k):
            return _mock_sync_response(
                modified=[{"transaction_id": "txn-1", "account_id": "acc-1", "amount": 50.00,
                           "date": "2026-08-20", "name": "NEW MERCHANT", "pending": False}]
            )

    _patch_client(monkeypatch, _Modified())

    # Act
    response = client.post("/api/plaid/sync", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert response.get_json()["totals"]["transactions_modified"] == 1
    db.session.refresh(txn)
    assert txn.amount == -50.00  # Plaid's +50 outflow negated
    assert txn.description == "NEW MERCHANT"
    assert txn.category_id == category["id"]  # survives the upsert


def test_sync_removed_deletes_the_transaction(client, test_user, auth_headers, monkeypatch):
    item = _seed_item(test_user, "item-a")
    account = Account(user_id=test_user.id, name="Checking", plaid_account_id="acc-1", plaid_item_id=item.id)
    db.session.add(account)
    db.session.flush()
    txn = Transaction(
        account_id=account.id, plaid_transaction_id="txn-1", posted_at="2026-08-01", amount=-10, description="X"
    )
    db.session.add(txn)
    db.session.commit()
    txn_id = txn.id

    class _Removed:
        def transactions_sync(self, *_a, **_k):
            return _mock_sync_response(removed=[{"transaction_id": "txn-1", "account_id": "acc-1"}])

    _patch_client(monkeypatch, _Removed())

    response = client.post("/api/plaid/sync", headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()["totals"]["transactions_removed"] == 1
    assert db.session.get(Transaction, txn_id) is None


# ---------------------------------------------------------------------------
# POST /api/plaid/sync — real Sandbox
# ---------------------------------------------------------------------------


@requires_plaid_sandbox
def test_sync_populates_accounts_and_transactions(client, test_user, auth_headers):
    _connect_with_dynamic_test_data(client, auth_headers)

    response = _sync_until_data_present(client, auth_headers)

    assert response.status_code == 200
    body = response.get_json()
    assert body["totals"]["accounts_synced"] >= 1
    assert body["totals"]["transactions_added"] >= 1
    assert body["ok"] is True

    accounts = Account.query.filter_by(user_id=test_user.id).all()
    assert len(accounts) == body["totals"]["accounts_synced"]
    assert all(a.plaid_account_id is not None for a in accounts)
    assert all(a.plaid_item_id is not None for a in accounts)  # tagged with its institution

    txns = Transaction.query.filter(Transaction.account_id.in_([a.id for a in accounts])).all()
    assert len(txns) >= 1


@requires_plaid_sandbox
def test_sync_is_incremental_on_second_call(client, test_user, auth_headers):
    _connect_with_dynamic_test_data(client, auth_headers)
    first = _sync_until_data_present(client, auth_headers)
    assert first.status_code == 200 and first.get_json()["totals"]["transactions_added"] >= 1

    deadline = time.monotonic() + _SANDBOX_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        settle = client.post("/api/plaid/sync", headers=auth_headers)
        assert settle.status_code == 200
        if settle.get_json()["totals"]["transactions_added"] == 0:
            break
        time.sleep(_SANDBOX_READY_POLL_INTERVAL_SECONDS)

    second = client.post("/api/plaid/sync", headers=auth_headers)
    assert second.status_code == 200
    body = second.get_json()
    assert body["totals"]["transactions_added"] == 0
    assert body["totals"]["transactions_modified"] == 0


# ---------------------------------------------------------------------------
# import cutoff — a fresh connection skips the historical backfill (changes/011)
# ---------------------------------------------------------------------------


def test_sync_skips_added_transactions_before_the_import_cutoff(client, test_user, auth_headers, monkeypatch):
    from datetime import date, timedelta

    cutoff = date.today()
    item = _seed_item(test_user, "item-cutoff", import_cutoff=cutoff)
    account = Account(user_id=test_user.id, name="Checking", plaid_account_id="acc-1", plaid_item_id=item.id)
    db.session.add(account)
    db.session.commit()

    old = (cutoff - timedelta(days=30)).isoformat()
    new = cutoff.isoformat()

    class _MixedAges:
        def transactions_sync(self, *_a, **_k):
            return _mock_sync_response(
                added=[
                    {"transaction_id": "old-1", "account_id": "acc-1", "amount": 5, "date": old, "name": "OLD", "pending": False},
                    {"transaction_id": "new-1", "account_id": "acc-1", "amount": 7, "date": new, "name": "NEW", "pending": False},
                ]
            )

    _patch_client(monkeypatch, _MixedAges())

    response = client.post("/api/plaid/sync", headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json()["totals"]["transactions_added"] == 1  # only the on-cutoff one
    descriptions = {t.description for t in Transaction.query.filter_by(account_id=account.id).all()}
    assert descriptions == {"NEW"}


def test_sync_with_null_cutoff_imports_all_history(client, test_user, auth_headers, monkeypatch):
    from datetime import date, timedelta

    item = _seed_item(test_user, "item-nocutoff", import_cutoff=None)
    account = Account(user_id=test_user.id, name="Checking", plaid_account_id="acc-1", plaid_item_id=item.id)
    db.session.add(account)
    db.session.commit()

    long_ago = (date.today() - timedelta(days=200)).isoformat()

    class _OldOnly:
        def transactions_sync(self, *_a, **_k):
            return _mock_sync_response(
                added=[{"transaction_id": "old-1", "account_id": "acc-1", "amount": 5, "date": long_ago, "name": "OLD", "pending": False}]
            )

    _patch_client(monkeypatch, _OldOnly())

    response = client.post("/api/plaid/sync", headers=auth_headers)
    assert response.get_json()["totals"]["transactions_added"] == 1


# ---------------------------------------------------------------------------
# Starting Balance on a brand-new account (changes/012)
# ---------------------------------------------------------------------------


def _mock_account(account_id, current, name="Checking", available=None, iso="USD"):
    return {
        "account_id": account_id,
        "name": name,
        "balances": {"current": current, "available": available, "iso_currency_code": iso},
    }


def _sync_response_with_accounts(accounts, added=None):
    body = _mock_sync_response(added=added)
    body["accounts"] = accounts
    return body


def test_sync_adds_starting_balance_for_a_new_account(client, test_user, auth_headers, monkeypatch):
    item = _seed_item(test_user, "item-sb")

    class _NewAccount:
        def transactions_sync(self, *_a, **_k):
            return _sync_response_with_accounts([_mock_account("acc-sb", 1500.00)])

    _patch_client(monkeypatch, _NewAccount())

    response = client.post("/api/plaid/sync", headers=auth_headers)
    assert response.status_code == 200

    account = Account.query.filter_by(user_id=test_user.id, plaid_account_id="acc-sb").first()
    starting = Transaction.query.filter_by(account_id=account.id, description="Starting Balance").all()
    assert len(starting) == 1
    assert starting[0].amount == account.balance == Decimal("1500.00")
    assert starting[0].is_income is True
    assert starting[0].plaid_transaction_id is None


def test_sync_does_not_add_a_second_starting_balance_on_re_sync(client, test_user, auth_headers, monkeypatch):
    item = _seed_item(test_user, "item-sb2")

    class _SameAccountTwice:
        def transactions_sync(self, *_a, **_k):
            return _sync_response_with_accounts([_mock_account("acc-sb", 1500.00)])

    _patch_client(monkeypatch, _SameAccountTwice())

    client.post("/api/plaid/sync", headers=auth_headers)
    client.post("/api/plaid/sync", headers=auth_headers)

    account = Account.query.filter_by(user_id=test_user.id, plaid_account_id="acc-sb").first()
    assert Transaction.query.filter_by(account_id=account.id, description="Starting Balance").count() == 1


def test_sync_skips_starting_balance_for_a_zero_balance_account(client, test_user, auth_headers, monkeypatch):
    item = _seed_item(test_user, "item-sb3")

    class _ZeroBalance:
        def transactions_sync(self, *_a, **_k):
            return _sync_response_with_accounts([_mock_account("acc-zero", 0)])

    _patch_client(monkeypatch, _ZeroBalance())

    client.post("/api/plaid/sync", headers=auth_headers)

    account = Account.query.filter_by(user_id=test_user.id, plaid_account_id="acc-zero").first()
    assert Transaction.query.filter_by(account_id=account.id, description="Starting Balance").count() == 0


# ---------------------------------------------------------------------------
# auto-categorization by prior choice (changes/013)
# ---------------------------------------------------------------------------


def _seed_account_and_category(user, category_name="Groceries"):
    from models import Category

    account = Account(user_id=user.id, name="Checking", plaid_account_id="acc-ac")
    category = Category(user_id=user.id, name=category_name)
    db.session.add_all([account, category])
    db.session.commit()
    return account, category


def test_sync_auto_categorizes_new_transaction_from_prior_same_merchant(client, test_user, auth_headers, monkeypatch):
    account, category = _seed_account_and_category(test_user)
    item = _seed_item(test_user, "item-ac")
    account.plaid_item_id = item.id
    # A prior transaction at "WHOLE FOODS" the user categorized.
    db.session.add(Transaction(
        account_id=account.id, plaid_transaction_id="prior", posted_at="2026-07-01",
        amount=-30, description="WHOLE FOODS", category_id=category.id,
    ))
    db.session.commit()

    class _NewSameMerchant:
        def transactions_sync(self, *_a, **_k):
            return _mock_sync_response(added=[
                {"transaction_id": "new-1", "account_id": "acc-ac", "amount": 12.0,
                 "date": "2026-08-15", "name": "WHOLE FOODS", "pending": False},
                {"transaction_id": "new-2", "account_id": "acc-ac", "amount": 8.0,
                 "date": "2026-08-16", "name": "NEVER SEEN BEFORE", "pending": False},
            ])

    _patch_client(monkeypatch, _NewSameMerchant())

    response = client.post("/api/plaid/sync", headers=auth_headers)
    assert response.status_code == 200

    matched = Transaction.query.filter_by(account_id=account.id, plaid_transaction_id="new-1").first()
    unmatched = Transaction.query.filter_by(account_id=account.id, plaid_transaction_id="new-2").first()
    assert matched.category_id == category.id  # auto-filled
    assert unmatched.category_id is None  # no prior match, left alone


def test_sync_does_not_recategorize_a_modified_transaction(client, test_user, auth_headers, monkeypatch):
    account, groceries = _seed_account_and_category(test_user, "Groceries")
    from models import Category
    dining = Category(user_id=test_user.id, name="Dining")
    db.session.add(dining)
    item = _seed_item(test_user, "item-ac2")
    account.plaid_item_id = item.id
    # An existing synced transaction the user filed under Dining.
    db.session.add(Transaction(
        account_id=account.id, plaid_transaction_id="existing", posted_at="2026-08-01",
        amount=-20, description="CHIPOTLE", category_id=dining.id,
    ))
    # A prior CHIPOTLE the user filed under Groceries (older).
    db.session.add(Transaction(
        account_id=account.id, plaid_transaction_id="older", posted_at="2026-07-01",
        amount=-19, description="CHIPOTLE", category_id=groceries.id,
    ))
    db.session.commit()

    class _ModifyExisting:
        def transactions_sync(self, *_a, **_k):
            return _mock_sync_response(modified=[
                {"transaction_id": "existing", "account_id": "acc-ac", "amount": 21.0,
                 "date": "2026-08-01", "name": "CHIPOTLE", "pending": False},
            ])

    _patch_client(monkeypatch, _ModifyExisting())

    client.post("/api/plaid/sync", headers=auth_headers)

    kept = Transaction.query.filter_by(account_id=account.id, plaid_transaction_id="existing").first()
    assert kept.category_id == dining.id  # user's choice untouched by the modify


# ---------------------------------------------------------------------------
# pending transactions are skipped until they post (changes/015)
# ---------------------------------------------------------------------------


def test_sync_skips_pending_added_transactions(client, test_user, auth_headers, monkeypatch):
    item = _seed_item(test_user, "item-pending")
    account = Account(user_id=test_user.id, name="Checking", plaid_account_id="acc-p", plaid_item_id=item.id)
    db.session.add(account)
    db.session.commit()

    class _PendingAndPosted:
        def transactions_sync(self, *_a, **_k):
            return _mock_sync_response(added=[
                {"transaction_id": "pend-1", "account_id": "acc-p", "amount": 5.0,
                 "date": "2026-08-20", "name": "STILL PENDING", "pending": True},
                {"transaction_id": "post-1", "account_id": "acc-p", "amount": 8.0,
                 "date": "2026-08-21", "name": "SETTLED", "pending": False},
            ])

    _patch_client(monkeypatch, _PendingAndPosted())

    response = client.post("/api/plaid/sync", headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()["totals"]["transactions_added"] == 1  # only the settled one

    descriptions = {t.description for t in Transaction.query.filter_by(account_id=account.id).all()}
    assert descriptions == {"SETTLED"}


def test_sync_imports_the_transaction_once_it_settles(client, test_user, auth_headers, monkeypatch):
    item = _seed_item(test_user, "item-settle")
    account = Account(user_id=test_user.id, name="Checking", plaid_account_id="acc-s", plaid_item_id=item.id)
    db.session.add(account)
    db.session.commit()

    class _PendingThenPosted:
        def __init__(self):
            self.calls = 0

        def transactions_sync(self, *_a, **_k):
            self.calls += 1
            if self.calls == 1:
                return _mock_sync_response(added=[
                    {"transaction_id": "t-1", "account_id": "acc-s", "amount": 12.0,
                     "date": "2026-08-20", "name": "COFFEE", "pending": True},
                ])
            return _mock_sync_response(modified=[
                {"transaction_id": "t-1", "account_id": "acc-s", "amount": 12.0,
                 "date": "2026-08-20", "name": "COFFEE", "pending": False},
            ])

    _patch_client(monkeypatch, _PendingThenPosted())

    first = client.post("/api/plaid/sync", headers=auth_headers)
    assert first.get_json()["totals"]["transactions_added"] == 0  # pending, skipped
    assert Transaction.query.filter_by(account_id=account.id).count() == 0

    second = client.post("/api/plaid/sync", headers=auth_headers)
    assert second.get_json()["totals"]["transactions_modified"] == 1  # now it settled
    row = Transaction.query.filter_by(account_id=account.id).one()
    assert row.description == "COFFEE"
    assert row.pending is False
