"""Policy must be enforced identically on every transaction entry point.

The only REST surface that can execute a transaction is ``POST /api/chat``; it
reaches vendors solely through the MCP ``execute_transaction`` business tool.
These tests run the same policy scenarios through REST chat and through MCP
directly (bypassing the orchestrator's own pre-check) and require the same
denial, with no persisted transaction and no vendor submission.

All vendors are simulated.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import apps.api.app.mcp_server.app as mcp_app
from apps.api.app.conversations import reset_conversations
from apps.api.app.database import SessionLocal
from apps.api.app.domain.transaction import Transaction
from apps.api.app.main import app
from policy.account_context import AccountContext, AccountType
from policy.engine import default_policy_engine
from vendor_fakes import (
    ScriptedVendor,
    delete_transactions,
    new_transaction_ids,
    success,
)

KNOWN = "08030000001"
UNKNOWN_ACCOUNT = "08039999999"


@pytest.fixture
def client() -> Iterator[TestClient]:
    reset_conversations()
    with TestClient(app) as c:
        yield c
    reset_conversations()


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> ScriptedVendor:
    scripted = ScriptedVendor(submit_script=(success("ref-policy"),))
    monkeypatch.setattr(
        mcp_app, "create_authenticated_adapter", lambda code, settings: scripted
    )
    return scripted


@pytest.fixture(autouse=True)
def cleanup() -> Iterator[None]:
    def snapshot() -> dict[str, set[UUID]]:
        with SessionLocal() as db:
            return {
                b: set(db.scalars(select(Transaction.id).where(Transaction.beneficiary == b)))
                for b in (KNOWN, UNKNOWN_ACCOUNT)
            }

    before = snapshot()
    yield
    for b, ids in before.items():
        with SessionLocal() as db:
            delete_transactions(db, new_transaction_ids(b, ids))


def set_account(monkeypatch, account_type: AccountType, balance: str) -> None:
    ctx = AccountContext(
        beneficiary=KNOWN, account_type=account_type, balance=Decimal(balance)
    )
    monkeypatch.setattr(
        default_policy_engine._account_contexts, "_contexts", {KNOWN: ctx}
    )


def via_chat(client: TestClient, beneficiary: str) -> dict:
    r = client.post(
        "/api/chat", json={"message": f"Buy ₦5,000 MTN airtime for {beneficiary}."}
    )
    assert r.status_code == 200, r.text
    return r.json()


def via_mcp(beneficiary: str) -> dict:
    out = mcp_app._execute_transaction(
        mcp_app.ExecuteTransactionRequest(
            service_type="airtime",
            product_type="airtime",
            network="MTN",
            beneficiary=beneficiary,
            amount="5000.00",
            idempotency_key=f"policy-{beneficiary}-{id(object())}",
        )
    )
    return out.model_dump(mode="json")


DENIALS = [
    pytest.param(UNKNOWN_ACCOUNT, None, "Account context not found", id="missing-account"),
    pytest.param(KNOWN, (AccountType.PREPAID, "100"), "Insufficient balance", id="insufficient-balance"),
    pytest.param(KNOWN, (AccountType.POSTPAID, "99999"), "Postpaid policy is not configured", id="postpaid"),
]


@pytest.mark.parametrize(("beneficiary", "account", "reason"), DENIALS)
def test_denials_are_identical_through_rest_and_mcp_without_vendor_activity(
    client, vendor, monkeypatch, beneficiary, account, reason
):
    if account is not None:
        set_account(monkeypatch, *account)
    with SessionLocal() as db:
        preexisting = set(
            db.scalars(select(Transaction.id).where(Transaction.beneficiary == beneficiary))
        )

    for body in (via_chat(client, beneficiary), via_mcp(beneficiary)):
        assert body["status"] == "denied"
        assert body["action"] == "deny"
        assert body["reason"] == reason
        assert body["message"] == reason
        assert body["transaction_id"] is None
        assert body["vendor_code"] is None
        assert body["vendor_reference"] is None

    assert vendor.submissions == [] and vendor.validations == 0
    with SessionLocal() as db:
        persisted = db.scalars(
            select(Transaction.id).where(Transaction.beneficiary == beneficiary)
        ).all()
    # A denial never persists a transaction (pre-existing KNOWN rows excluded).
    assert not [i for i in persisted if i not in preexisting]


def test_allowed_request_executes_through_rest_and_mcp(client, vendor):
    chat = via_chat(client, KNOWN)
    assert chat["status"] == "success" and chat["action"] == "allow"
    mcp = via_mcp(KNOWN)
    assert mcp["status"] == "success" and mcp["action"] == "allow"
    assert len(vendor.submissions) == 2  # first is terminal, so a new purchase


def test_balance_boundary_equal_to_amount_is_allowed(client, vendor, monkeypatch):
    set_account(monkeypatch, AccountType.PREPAID, "5000")
    assert via_chat(client, KNOWN)["action"] == "allow"
    assert via_mcp(KNOWN)["action"] == "allow"


def test_only_known_routes_can_reach_transaction_execution():
    """Adding a route forces a conscious policy decision (and a parity test)."""
    paths = app.openapi()["paths"]
    post_paths = {path for path, ops in paths.items() if "post" in ops}
    assert post_paths == {
        "/api/chat",
        "/api/demo/scenarios",
        "/api/demo/scenarios/reset",
    }
