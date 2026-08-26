"""Integration tests for spec/plaid-sync.md.

Real Sandbox calls for the connect/sync happy-path and error tests, same
mock-boundary reasoning as tests/test_plaid_connect.py (Plaid Sandbox is
safe for repeated automated reruns). Two scenarios are deliberately mocked
at the SDK layer instead, per context/testing.md's fallback rule ("no
reliably repeatable safe test environment" for this specific scenario):

- A `removed` transaction: Plaid's `user_transactions_dynamic` Sandbox test
  user does produce evolving data, but on a real-time cadence (observed:
  no change across calls a few seconds apart) — not fast enough to trigger
  a real removal within one automated test run.
- A `modified` transaction with a changed amount: same reasoning, plus
  this is also the test that pins down the exact sign-convention
  requirement (Plaid: positive = outflow; this app: positive = inflow —
  see spec/plaid-sync.md's Notes) with a fully-controlled, exact expected
  value rather than an unpredictable live one.

Everything else in both mocked tests is real: real connection, real first
sync, real DB state — only the second `transactions_sync` call is mocked.
"""

import os
import time

import plaid
import pytest
from models import Account, Transaction, db
from plaid.api import plaid_api
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
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

# Sandbox test user whose data evolves over real time — chosen specifically
# so this slice's tests exercise real transaction volume, not the static
# always-identical set the default user_good/pass_good would give.
_DYNAMIC_USER_OPTIONS = SandboxPublicTokenCreateRequestOptions(
    override_username="user_transactions_dynamic", override_password="pass_good"
)

# Sandbox item initialization is async — see spec/plaid-sync.md's Notes.
# A fresh connection can report zero transactions for several seconds.
_SANDBOX_READY_TIMEOUT_SECONDS = 30
_SANDBOX_READY_POLL_INTERVAL_SECONDS = 3


def _plaid_sandbox_client():
    configuration = plaid.Configuration(
        host=plaid.Environment.Sandbox,
        api_key={"clientId": os.environ["PLAID_CLIENT_ID"], "secret": os.environ["PLAID_SECRET"]},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def _connect_with_dynamic_test_data(client, auth_headers):
    """Connects the test user via a real Sandbox exchange, using the
    dynamic test user so there's real transaction data to sync."""
    request = SandboxPublicTokenCreateRequest(
        institution_id=SANDBOX_INSTITUTION_ID,
        initial_products=[Products("transactions")],
        options=_DYNAMIC_USER_OPTIONS,
    )
    public_token = _plaid_sandbox_client().sandbox_public_token_create(request)["public_token"]
    connect_response = client.post("/api/plaid/connect", json={"public_token": public_token}, headers=auth_headers)
    assert connect_response.status_code == 200, "test setup failed: real /connect call did not succeed"


def _sync_until_data_present(client, auth_headers):
    """POSTs /api/plaid/sync, retrying while Sandbox item initialization is
    still in progress (see spec/plaid-sync.md's Notes) — a 200 with
    all-zero counts isn't an error, just not ready yet. Returns the first
    response that actually contains data, or the last response if the
    timeout is hit (the test's own assertions will then fail meaningfully
    on that response rather than this helper hiding a real problem)."""
    deadline = time.monotonic() + _SANDBOX_READY_TIMEOUT_SECONDS
    response = None
    while time.monotonic() < deadline:
        response = client.post("/api/plaid/sync", headers=auth_headers)
        if response.status_code != 200:
            # Not a "still initializing" state — a real failure (or, pre-
            # build, a 404). Return immediately so the caller's own
            # assertion produces a clear message instead of this helper
            # crashing on a non-JSON/error body.
            return response
        body = response.get_json()
        if body.get("transactions_added", 0) > 0:
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


# ---------------------------------------------------------------------------
# POST /api/plaid/sync
# ---------------------------------------------------------------------------


def test_sync_without_token_returns_401(client, test_user):
    # Act
    response = client.post("/api/plaid/sync")

    # Assert
    assert response.status_code == 401


def test_sync_as_demo_user_returns_403(client, demo_auth_headers):
    # Act
    response = client.post("/api/plaid/sync", headers=demo_auth_headers)

    # Assert
    assert response.status_code == 403


def test_sync_without_connection_returns_409(client, test_user, auth_headers):
    # Act — test_user has never connected, no plaid_access_token_encrypted
    response = client.post("/api/plaid/sync", headers=auth_headers)

    # Assert
    assert response.status_code == 409


@requires_plaid_sandbox
def test_sync_plaid_outage_returns_502(client, test_user, auth_headers, monkeypatch):
    # Arrange — a real connection (needed to get past the 409 check), but
    # the sync call itself is mocked to simulate a network-level failure —
    # a raw exception, not an ApiException, matching plaid-connect.md's
    # "real outage, not just an HTTP error status" correction.
    _connect_with_dynamic_test_data(client, auth_headers)

    class _FailingPlaidClient:
        def transactions_sync(self, *_args, **_kwargs):
            raise ConnectionError("simulated network failure")

    import plaid_api as plaid_api_module

    monkeypatch.setattr(plaid_api_module, "_plaid_client", lambda: _FailingPlaidClient())

    # Act
    response = client.post("/api/plaid/sync", headers=auth_headers)

    # Assert — sanitized error, not a raw 500
    assert response.status_code == 502
    assert "error" in response.get_json()


@requires_plaid_sandbox
def test_sync_populates_accounts_and_transactions(client, test_user, auth_headers):
    # Arrange
    _connect_with_dynamic_test_data(client, auth_headers)

    # Act
    response = _sync_until_data_present(client, auth_headers)

    # Assert
    assert response.status_code == 200
    body = response.get_json()
    assert body["accounts_synced"] >= 1
    assert body["transactions_added"] >= 1

    # Assert side effects — real rows, not just a response shape
    accounts = Account.query.filter_by(user_id=test_user.id).all()
    assert len(accounts) == body["accounts_synced"], "accounts_synced must count distinct accounts, not per-page sum"
    assert all(a.plaid_account_id is not None for a in accounts)

    synced_account_ids = [a.id for a in accounts]
    transactions = Transaction.query.filter(Transaction.account_id.in_(synced_account_ids)).all()
    assert len(transactions) >= 1
    assert all(t.plaid_transaction_id is not None for t in transactions)


@requires_plaid_sandbox
def test_sync_is_incremental_on_second_call(client, test_user, auth_headers):
    # Arrange — real connection, then sync repeatedly until Plaid's
    # asynchronous historical update finishes landing (a second sync can
    # legitimately report MORE transactions while it's still arriving —
    # that's real new data, not a cursor failure; observed empirically as
    # a race that failed this test ~1 run in 3 when it asserted "second
    # call == 0" immediately). Steady state = a sync that reports nothing
    # new. Two setup corrections were made to this test while confirming
    # green, both to setup/timing, neither to the behavior under test:
    # (1) it originally omitted the connect step and 409'd; (2) the
    # historical-update race described above.
    _connect_with_dynamic_test_data(client, auth_headers)
    first_response = _sync_until_data_present(client, auth_headers)
    assert first_response.status_code == 200, f"setup sync failed: {first_response.status_code}"
    assert first_response.get_json()["transactions_added"] >= 1

    deadline = time.monotonic() + _SANDBOX_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        settle_response = client.post("/api/plaid/sync", headers=auth_headers)
        assert settle_response.status_code == 200
        if settle_response.get_json()["transactions_added"] == 0:
            break
        time.sleep(_SANDBOX_READY_POLL_INTERVAL_SECONDS)

    # Act — sync once more from steady state
    second_response = client.post("/api/plaid/sync", headers=auth_headers)

    # Assert — proves the cursor was persisted and reused: a full
    # first-time pull would show the whole history as "added" again
    # (100s of transactions), an incremental pull with a saved cursor
    # shows nothing new.
    assert second_response.status_code == 200
    body = second_response.get_json()
    assert body["transactions_added"] == 0
    assert body["transactions_modified"] == 0


@requires_plaid_sandbox
def test_sync_upserts_modified_transaction_without_touching_category(client, test_user, auth_headers, monkeypatch):
    # Arrange — a real transaction, real category, real categorization
    # through the actual app endpoints (not a raw DB write)
    _connect_with_dynamic_test_data(client, auth_headers)
    first_response = _sync_until_data_present(client, auth_headers)
    assert first_response.status_code == 200, f"setup sync failed: {first_response.status_code}"
    assert first_response.get_json()["transactions_added"] >= 1

    account = Account.query.filter_by(user_id=test_user.id).first()
    transaction = Transaction.query.filter_by(account_id=account.id).first()

    category_response = client.post("/api/categories", json={"name": "Groceries"}, headers=auth_headers)
    category_id = category_response.get_json()["id"]
    patch_response = client.patch(
        f"/api/transactions/{transaction.id}", json={"category_id": category_id}, headers=auth_headers
    )
    assert patch_response.status_code == 200

    # Act — mock a second sync reporting that same transaction as
    # "modified" with a different amount. Plaid's amount convention is
    # positive-=-outflow; this app's is positive-=-inflow (see
    # spec/plaid-sync.md's Notes) — 50.00 here must land as -50.00 in our
    # column, the exact assertion this test is really checking.
    import plaid_api as plaid_api_module

    mock_response = _mock_sync_response(
        modified=[
            {
                "transaction_id": transaction.plaid_transaction_id,
                "account_id": account.plaid_account_id,
                "amount": 50.00,
                "date": "2026-08-20",
                "name": "UPDATED MERCHANT NAME",
                "pending": False,
            }
        ]
    )

    class _MockPlaidClient:
        def transactions_sync(self, *_args, **_kwargs):
            return mock_response

    monkeypatch.setattr(plaid_api_module, "_plaid_client", lambda: _MockPlaidClient())

    response = client.post("/api/plaid/sync", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert response.get_json()["transactions_modified"] == 1

    db.session.refresh(transaction)
    assert transaction.amount == -50.00, "Plaid's amount must be negated to match this app's sign convention"
    assert transaction.description == "UPDATED MERCHANT NAME"
    assert transaction.category_id == category_id, "category_id must survive an upsert from a modified sync entry"


@requires_plaid_sandbox
def test_sync_deletes_removed_transaction(client, test_user, auth_headers, monkeypatch):
    # Arrange — a real transaction to later report as removed
    _connect_with_dynamic_test_data(client, auth_headers)
    first_response = _sync_until_data_present(client, auth_headers)
    assert first_response.status_code == 200, f"setup sync failed: {first_response.status_code}"
    assert first_response.get_json()["transactions_added"] >= 1

    account = Account.query.filter_by(user_id=test_user.id).first()
    transaction = Transaction.query.filter_by(account_id=account.id).first()
    transaction_id = transaction.id
    removed_plaid_id = transaction.plaid_transaction_id

    # Act — mock a second sync reporting that transaction as removed
    import plaid_api as plaid_api_module

    mock_response = _mock_sync_response(
        removed=[{"transaction_id": removed_plaid_id, "account_id": account.plaid_account_id}]
    )

    class _MockPlaidClient:
        def transactions_sync(self, *_args, **_kwargs):
            return mock_response

    monkeypatch.setattr(plaid_api_module, "_plaid_client", lambda: _MockPlaidClient())

    response = client.post("/api/plaid/sync", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    assert response.get_json()["transactions_removed"] == 1
    assert db.session.get(Transaction, transaction_id) is None
