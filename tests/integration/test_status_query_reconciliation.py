"""Regression tests: a failing vendor status query must never lose or misreport
a transaction.

Previously the exception escaped ``_reconcile`` after the row had been committed
as ``INVESTIGATING``. MCP then reported an opaque tool error, so callers never
learned the transaction id, and (because every chat request gets a fresh
idempotency key) a retry could submit the purchase a second time.

These tests pin the corrected contract at every layer:

* persistence: the row stays ``UNKNOWN`` with a safe diagnostic, keeps its id,
  vendor identity and vendor details, and is never resubmitted;
* MCP business tools: an unresolved transaction is *returned*, not raised;
* REST ``/api/chat``: HTTP 200 ``unknown`` with the existing transaction id, and
  the pre-existing HTTP 502 mapping for genuine tool errors is unchanged;
* conversation mode: the real transaction id is surfaced.

All vendor behaviour is simulated; no real airtime purchase is possible.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import apps.api.app.mcp_server.app as mcp_app
from agent.orchestrator.service import MCPBusinessToolError, MCPClientBusinessTools
from apps.api.app.conversations import reset_conversations
from apps.api.app.database import SessionLocal
from apps.api.app.domain.transaction import Transaction, TransactionState
from apps.api.app.main import app
from switcher.transactions.execution_service import TransactionExecutionService
from switcher.transactions.persistence_service import (
    STATUS_QUERY_FAILED_CODE,
    STATUS_QUERY_FAILED_MESSAGE,
    PersistedTransactionExecutionService,
)
from vendor_fakes import (
    ScriptedVendor,
    delete_transactions,
    failed,
    new_transaction_ids,
    success,
    unique_beneficiary,
    unknown,
)
from vendors.base.models import VendorTransactionResult, VendorTransactionStatus

SECRET = "hunter2-db-password"
LEAKY_ERROR = ConnectionError(
    f"vendor-host.internal:5432 refused connection (password={SECRET})"
)
POLICY_BENEFICIARY = "08030000001"  # the only account known to the demo policy
CHAT_MESSAGE = "Buy ₦5,000 MTN airtime for 08030000001."


# --------------------------------------------------------------------------
# fixtures / helpers
# --------------------------------------------------------------------------


@pytest.fixture
def session() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


@pytest.fixture
def created_ids(session: Session) -> Iterator[list[UUID]]:
    ids: list[UUID] = []
    yield ids
    delete_transactions(session, ids)


@pytest.fixture
def policy_account_cleanup() -> Iterator[None]:
    """Remove only transactions created for the policy account during a test."""
    with SessionLocal() as db:
        before = set(
            db.scalars(
                select(Transaction.id).where(
                    Transaction.beneficiary == POLICY_BENEFICIARY
                )
            )
        )
    yield
    created = new_transaction_ids(POLICY_BENEFICIARY, before)
    with SessionLocal() as db:
        delete_transactions(db, created)


@pytest.fixture
def client() -> Iterator[TestClient]:
    reset_conversations()
    with TestClient(app) as test_client:
        yield test_client
    reset_conversations()


def make_transaction(beneficiary: str) -> Transaction:
    from decimal import Decimal

    return Transaction(
        product_type="airtime",
        network="MTN",
        beneficiary=beneficiary,
        amount=Decimal("5000.00"),
    )


def persisted(transaction_id: UUID) -> Transaction:
    with SessionLocal() as db:
        row = db.get(Transaction, transaction_id)
        assert row is not None
        db.expunge(row)
        return row


def timed_out_vendor(**kwargs) -> ScriptedVendor:
    """Submission times out (outcome uncertain); status queries are scripted."""
    return ScriptedVendor(submit_script=(TimeoutError("scripted timeout"),), **kwargs)


def install_vendor(monkeypatch: pytest.MonkeyPatch, vendor: ScriptedVendor) -> None:
    """Route the MCP business path to a scripted vendor (all vendor codes)."""
    monkeypatch.setattr(
        mcp_app,
        "create_authenticated_adapter",
        lambda vendor_code, settings: vendor,
    )


# --------------------------------------------------------------------------
# persistence layer
# --------------------------------------------------------------------------


def test_initial_status_query_failure_keeps_transaction_unknown_and_identified(
    session: Session,
    created_ids: list[UUID],
    caplog: pytest.LogCaptureFixture,
):
    vendor = timed_out_vendor(query_script=(LEAKY_ERROR,))
    transaction = make_transaction(unique_beneficiary())
    service = PersistedTransactionExecutionService(
        session, TransactionExecutionService(vendor)
    )

    with caplog.at_level(logging.WARNING):
        result = service.execute(transaction)  # must not raise
    created_ids.append(result.id)

    # Original identity preserved; unconfirmed, never terminal.
    assert result.id == transaction.id
    assert result.state == TransactionState.UNKNOWN
    assert result.vendor_code == "vendor_a"
    # Original investigation context is kept; the failure is recorded safely.
    assert result.error_message == "Vendor submission outcome is uncertain"
    assert result.error_code == STATUS_QUERY_FAILED_CODE
    # Exactly one vendor submission, one status query, no resubmission.
    assert vendor.submissions == [result.id]
    assert vendor.queries == [result.id]

    # What is persisted (and so what any client can see) holds no secrets.
    reloaded = persisted(result.id)
    assert reloaded.state == TransactionState.UNKNOWN
    for visible in (reloaded.error_code, reloaded.error_message):
        assert SECRET not in (visible or "")
        assert "vendor-host.internal" not in (visible or "")

    # Observable: the failure is logged server-side with id and error type.
    records = [r for r in caplog.records if "status query failed" in r.getMessage()]
    assert len(records) == 1
    assert str(result.id) in records[0].getMessage()
    assert "ConnectionError" in records[0].getMessage()


def test_query_failure_preserves_vendor_details_and_uses_default_message(
    session: Session,
    created_ids: list[UUID],
):
    vendor = ScriptedVendor(
        submit_script=(
            VendorTransactionResult(
                status=VendorTransactionStatus.ACCEPTED,
                vendor_reference="ref-accepted-1",
                raw_response={"accepted": True},
            ),
        ),
        query_script=(LEAKY_ERROR,),
    )
    service = PersistedTransactionExecutionService(
        session, TransactionExecutionService(vendor)
    )
    submitted = service.execute(make_transaction(unique_beneficiary()))
    created_ids.append(submitted.id)
    assert submitted.state == TransactionState.SUBMITTED

    result = service.investigate(submitted)

    assert result.id == submitted.id
    assert result.state == TransactionState.UNKNOWN
    assert result.vendor_reference == "ref-accepted-1"
    assert result.raw_vendor_response == {"accepted": True}
    assert result.error_code == STATUS_QUERY_FAILED_CODE
    # No earlier message existed, so the safe default is used.
    assert result.error_message == STATUS_QUERY_FAILED_MESSAGE
    assert vendor.submissions == [submitted.id]


def test_repeated_query_failures_are_safe_and_never_resubmit(
    session: Session,
    created_ids: list[UUID],
    caplog: pytest.LogCaptureFixture,
):
    vendor = timed_out_vendor(query_script=(LEAKY_ERROR,))
    service = PersistedTransactionExecutionService(
        session, TransactionExecutionService(vendor)
    )
    first = service.execute(make_transaction(unique_beneficiary()))
    created_ids.append(first.id)

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            again = service.investigate(first)
            assert again.id == first.id
            assert again.state == TransactionState.UNKNOWN
            assert again.error_code == STATUS_QUERY_FAILED_CODE

    # 1 query during execute + 3 explicit investigations; still one submission.
    assert len(vendor.queries) == 4
    assert vendor.submissions == [first.id]
    # Every failure is observable: one log record per failed query (the initial
    # one during execute plus the three explicit investigations).
    failures = [r for r in caplog.records if "status query failed" in r.getMessage()]
    assert len(failures) == len(vendor.queries) == 4
    assert persisted(first.id).state == TransactionState.UNKNOWN


def test_later_successful_query_resolves_the_original_transaction(
    session: Session,
    created_ids: list[UUID],
):
    vendor = timed_out_vendor(query_script=(LEAKY_ERROR,))
    service = PersistedTransactionExecutionService(
        session, TransactionExecutionService(vendor)
    )
    first = service.execute(make_transaction(unique_beneficiary()))
    created_ids.append(first.id)
    assert first.state == TransactionState.UNKNOWN

    vendor.set_query_script(success("ref-confirmed"))
    resolved = service.investigate(first)

    assert resolved.id == first.id
    assert resolved.state == TransactionState.SUCCESS
    assert resolved.vendor_reference == "ref-confirmed"
    # A confirmed outcome carries no stale failure markers.
    assert resolved.error_code is None
    assert resolved.error_message is None
    assert vendor.submissions == [first.id]


def test_later_confirmed_vendor_failure_resolves_to_failed_without_stale_code(
    session: Session,
    created_ids: list[UUID],
):
    vendor = timed_out_vendor(query_script=(LEAKY_ERROR,))
    service = PersistedTransactionExecutionService(
        session, TransactionExecutionService(vendor)
    )
    first = service.execute(make_transaction(unique_beneficiary()))
    created_ids.append(first.id)

    vendor.set_query_script(failed("Vendor rejected the purchase"))
    resolved = service.investigate(first)

    assert resolved.state == TransactionState.FAILED
    assert resolved.error_message == "Vendor rejected the purchase"
    assert resolved.error_code is None
    assert vendor.submissions == [first.id]


def test_adapter_failure_during_reconciliation_does_not_strand_investigating(
    session: Session,
    created_ids: list[UUID],
):
    vendor = timed_out_vendor(query_script=(unknown(),))
    first = PersistedTransactionExecutionService(
        session, TransactionExecutionService(vendor)
    ).execute(make_transaction(unique_beneficiary()))
    created_ids.append(first.id)
    assert first.state == TransactionState.UNKNOWN

    def broken_factory() -> TransactionExecutionService:
        raise RuntimeError("adapter authentication unavailable")

    broken = PersistedTransactionExecutionService(session, broken_factory)
    with pytest.raises(RuntimeError):
        broken.investigate(first)

    # The row was not moved into INVESTIGATING by the failed attempt.
    assert persisted(first.id).state == TransactionState.UNKNOWN
    assert vendor.submissions == [first.id]


# --------------------------------------------------------------------------
# MCP business tools
# --------------------------------------------------------------------------


def test_mcp_execute_returns_unknown_with_transaction_id_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
    policy_account_cleanup: None,
):
    vendor = timed_out_vendor(query_script=(LEAKY_ERROR,))
    install_vendor(monkeypatch, vendor)

    output = mcp_app._execute_transaction(
        mcp_app.ExecuteTransactionRequest(
            service_type="airtime",
            product_type="airtime",
            network="MTN",
            beneficiary=POLICY_BENEFICIARY,
            amount="5000.00",
            idempotency_key="status-query-mcp-001",
        )
    )

    assert output.status == "unknown"
    assert output.action == "allow"
    assert output.transaction_id is not None
    assert output.vendor_code == "vendor_a"
    assert SECRET not in output.message
    assert "vendor-host.internal" not in output.message
    assert persisted(output.transaction_id).error_code == STATUS_QUERY_FAILED_CODE
    assert vendor.submissions == [output.transaction_id]


def test_mcp_status_lookup_reports_unknown_then_resolves(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    created_ids: list[UUID],
):
    vendor = timed_out_vendor(query_script=(LEAKY_ERROR,))
    install_vendor(monkeypatch, vendor)
    first = PersistedTransactionExecutionService(
        session, TransactionExecutionService(vendor)
    ).execute(make_transaction(unique_beneficiary()))
    created_ids.append(first.id)
    request = mcp_app.GetTransactionStatusRequest(transaction_id=first.id)

    still_unknown = mcp_app._get_transaction_status(request)  # must not raise
    assert still_unknown.transaction_id == first.id
    assert still_unknown.status == "unknown"
    assert SECRET not in (still_unknown.error_message or "")

    vendor.set_query_script(success("ref-late"))
    resolved = mcp_app._get_transaction_status(request)
    assert resolved.transaction_id == first.id
    assert resolved.status == "success"
    assert resolved.vendor_reference == "ref-late"
    assert vendor.submissions == [first.id]


# --------------------------------------------------------------------------
# REST (/api/chat) and conversation mode
# --------------------------------------------------------------------------


def test_chat_execute_reports_unknown_with_existing_transaction_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    policy_account_cleanup: None,
):
    vendor = timed_out_vendor(query_script=(LEAKY_ERROR,))
    install_vendor(monkeypatch, vendor)

    response = client.post("/api/chat", json={"message": CHAT_MESSAGE})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "unknown"
    assert body["action"] == "allow"
    transaction_id = UUID(body["transaction_id"])  # real id, not null
    assert persisted(transaction_id).state == TransactionState.UNKNOWN
    assert "could not be confirmed" in body["explanation"]
    assert "retry" not in body["explanation"].lower()
    assert SECRET not in response.text
    assert "vendor-host.internal" not in response.text
    assert vendor.submissions == [transaction_id]


def test_conversation_mode_surfaces_the_real_transaction_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    policy_account_cleanup: None,
):
    vendor = timed_out_vendor(query_script=(LEAKY_ERROR,))
    install_vendor(monkeypatch, vendor)

    first = client.post(
        "/api/chat", json={"message": CHAT_MESSAGE, "mode": "conversation"}
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json()["conversation_id"]
    done = client.post(
        "/api/chat",
        json={
            "action": "confirm",
            "mode": "conversation",
            "conversation_id": conversation_id,
        },
    )

    assert done.status_code == 200, done.text
    result = done.json()["result"]
    assert result["status"] == "unknown"
    assert result["transaction_id"] is not None
    assert persisted(UUID(result["transaction_id"])).state == TransactionState.UNKNOWN
    assert vendor.submissions == [UUID(result["transaction_id"])]


def test_genuine_tool_errors_keep_their_existing_http_mapping(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """Unrelated tool failures remain HTTP 502 (execute) / truthful UNKNOWN
    without an invented id (conversation); only the status-query path changed."""

    async def failing(self, **kwargs):
        raise MCPBusinessToolError("MCP tool execute_transaction returned an error")

    monkeypatch.setattr(MCPClientBusinessTools, "execute_transaction", failing)

    execute = client.post("/api/chat", json={"message": CHAT_MESSAGE})
    assert execute.status_code == 502
    assert execute.json() == {"detail": "Transaction execution could not be completed"}

    first = client.post(
        "/api/chat", json={"message": CHAT_MESSAGE, "mode": "conversation"}
    )
    conversation_id = first.json()["conversation_id"]
    done = client.post(
        "/api/chat",
        json={
            "action": "confirm",
            "mode": "conversation",
            "conversation_id": conversation_id,
        },
    )
    assert done.status_code == 200
    assert done.json()["result"]["status"] == "unknown"
    assert done.json()["result"]["transaction_id"] is None
