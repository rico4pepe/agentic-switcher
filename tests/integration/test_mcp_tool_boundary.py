"""Wire-level tests for the MCP tool boundary.

These tests call the mounted ``/mcp`` endpoint exactly as an external MCP
client would and verify that the boundary stays business-level:

* invalid input is rejected before any transaction or vendor operation exists;
* undeclared arguments cannot select a vendor (the MCP SDK ignores them rather
  than rejecting them, so the invariant is "no influence", not "rejected");
* investigation always follows the persisted vendor, never client input;
* internal vendor operations cannot be invoked as tools.

Schema-level checks live in ``test_mcp_mount.py`` and need no database. Like the
other MCP integration tests, this module needs the migrated and seeded
PostgreSQL test database, and it removes only the rows it creates.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from apps.api.app.database import SessionLocal, engine
from apps.api.app.domain.transaction import Transaction, TransactionState
from apps.api.app.main import app
from switcher.routing import reset_vendor_availability, set_vendor_availability
from vendors.base.models import TransactionExecutionRequest, VendorTransactionResult
from vendors.vendor_a.operation_ledger import (
    PostgresVendorAOperationLedger,
    VendorAOperationRecord,
)
from vendors.vendor_b.operation_ledger import (
    PostgresVendorBOperationLedger,
    VendorBOperationRecord,
)


@dataclass
class VendorLedgerCalls:
    """Vendor ledger operations observed while a test ran."""

    a_submits: list[UUID] = field(default_factory=list)
    b_submits: list[UUID] = field(default_factory=list)
    a_queries: list[UUID] = field(default_factory=list)
    b_queries: list[UUID] = field(default_factory=list)

    @property
    def any_vendor_call(self) -> bool:
        return bool(
            self.a_submits or self.b_submits or self.a_queries or self.b_queries
        )


@pytest.fixture
def postgres_session() -> Iterator[Session]:
    assert engine.dialect.name == "postgresql"
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def created_transaction_ids(postgres_session: Session) -> Iterator[list[UUID]]:
    """Delete only the transactions (and both vendor ledger rows) a test created."""
    transaction_ids: list[UUID] = []
    try:
        yield transaction_ids
    finally:
        postgres_session.rollback()
        if transaction_ids:
            postgres_session.execute(
                delete(VendorAOperationRecord).where(
                    VendorAOperationRecord.transaction_id.in_(transaction_ids)
                )
            )
            postgres_session.execute(
                delete(VendorBOperationRecord).where(
                    VendorBOperationRecord.transaction_id.in_(transaction_ids)
                )
            )
            postgres_session.execute(
                delete(Transaction).where(Transaction.id.in_(transaction_ids))
            )
            postgres_session.commit()


@pytest.fixture
def vendor_ledger_calls(monkeypatch: pytest.MonkeyPatch) -> VendorLedgerCalls:
    """Record every submit/query reaching either vendor ledger."""
    calls = VendorLedgerCalls()

    def instrument(
        ledger_class: type,
        submits: list[UUID],
        queries: list[UUID],
    ) -> None:
        original_submit = ledger_class.submit
        original_query = ledger_class.query

        def counted_submit(
            ledger: Any,
            request: TransactionExecutionRequest,
        ) -> VendorTransactionResult:
            submits.append(request.transaction_id)
            return original_submit(ledger, request)

        def counted_query(
            ledger: Any,
            transaction_id: UUID,
        ) -> VendorTransactionResult:
            queries.append(transaction_id)
            return original_query(ledger, transaction_id)

        monkeypatch.setattr(ledger_class, "submit", counted_submit)
        monkeypatch.setattr(ledger_class, "query", counted_query)

    instrument(PostgresVendorAOperationLedger, calls.a_submits, calls.a_queries)
    instrument(PostgresVendorBOperationLedger, calls.b_submits, calls.b_queries)
    return calls


def call_mcp_tool(name: str, arguments: dict[str, object]) -> dict[str, Any]:
    """Call a tool over HTTP and return its MCP result.

    A protocol-level JSON-RPC error is normalized to an ``isError`` result:
    for a boundary test both mean the call was rejected.
    """
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": arguments,
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    },
                },
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Method": "tools/call",
                "Mcp-Name": name,
                "Mcp-Protocol-Version": "2026-07-28",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    if "error" in body:
        return {
            "isError": True,
            "content": [{"type": "text", "text": str(body["error"])}],
        }
    return body["result"]


def execute_arguments(
    idempotency_key: str,
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    """Valid execute arguments; an override value of ``None`` removes the field."""
    arguments: dict[str, object] = {
        "service_type": "airtime",
        "product_type": "airtime",
        "network": "MTN",
        "beneficiary": "08030000001",
        "amount": "5000.00",
        "idempotency_key": idempotency_key,
    }
    for name, value in (overrides or {}).items():
        if value is None:
            arguments.pop(name, None)
        else:
            arguments[name] = value
    return arguments


def record_result_id(
    result: dict[str, Any],
    transaction_ids: list[UUID],
) -> UUID:
    transaction_id = UUID(str(result["structuredContent"]["transaction_id"]))
    transaction_ids.append(transaction_id)
    return transaction_id


def transactions_with_key(session: Session, idempotency_key: str) -> int:
    return session.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.idempotency_key == idempotency_key)
    )


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"amount": "0"}, id="amount-zero-string"),
        pytest.param({"amount": "-1"}, id="amount-negative-string"),
        pytest.param({"amount": 0}, id="amount-zero-number"),
        pytest.param({"amount": -5}, id="amount-negative-number"),
        pytest.param({"amount": "abc"}, id="amount-not-a-number"),
        pytest.param({"amount": None}, id="amount-missing"),
        pytest.param({"beneficiary": ""}, id="beneficiary-empty"),
        pytest.param({"beneficiary": "1" * 101}, id="beneficiary-too-long"),
        pytest.param({"product_type": ""}, id="product-type-empty"),
        pytest.param({"network": "N" * 51}, id="network-too-long"),
        pytest.param({"idempotency_key": ""}, id="idempotency-key-empty"),
        pytest.param({"idempotency_key": "k" * 256}, id="idempotency-key-too-long"),
    ],
)
def test_invalid_execute_arguments_are_rejected_without_side_effects(
    overrides: dict[str, object],
    postgres_session: Session,
    vendor_ledger_calls: VendorLedgerCalls,
):
    arguments = execute_arguments(f"mcp-boundary-invalid-{uuid4()}", overrides)

    result = call_mcp_tool("execute_transaction", arguments)

    assert result["isError"] is True
    assert (
        transactions_with_key(postgres_session, str(arguments["idempotency_key"])) == 0
    )
    assert not vendor_ledger_calls.any_vendor_call


@pytest.mark.parametrize(
    ("injected", "unavailable_vendor", "expected_vendor"),
    [
        pytest.param({"vendor_code": "vendor_b"}, None, "vendor_a", id="vendor_code"),
        pytest.param({"vendor": "vendor_b"}, None, "vendor_a", id="vendor"),
        pytest.param({"adapter": "vendor_b"}, None, "vendor_a", id="adapter"),
        pytest.param({"unexpected_field": "x"}, None, "vendor_a", id="unknown-field"),
        pytest.param(
            {"vendor_code": "vendor_a"},
            "vendor_a",
            "vendor_b",
            id="cannot-force-unavailable-vendor",
        ),
    ],
)
def test_undeclared_arguments_cannot_influence_vendor_selection(
    injected: dict[str, object],
    unavailable_vendor: str | None,
    expected_vendor: str,
    postgres_session: Session,
    created_transaction_ids: list[UUID],
    vendor_ledger_calls: VendorLedgerCalls,
):
    key = f"mcp-boundary-injection-{uuid4()}"
    if unavailable_vendor is not None:
        set_vendor_availability(unavailable_vendor, False)
    try:
        result = call_mcp_tool(
            "execute_transaction",
            {**execute_arguments(key), **injected},
        )
    finally:
        reset_vendor_availability()

    if result.get("isError") is True:
        # A stricter SDK may reject undeclared fields outright. That also keeps
        # the client from choosing a vendor, provided nothing was executed.
        assert transactions_with_key(postgres_session, key) == 0
        assert not vendor_ledger_calls.any_vendor_call
        return

    transaction_id = record_result_id(result, created_transaction_ids)
    submitted = {
        "vendor_a": vendor_ledger_calls.a_submits,
        "vendor_b": vendor_ledger_calls.b_submits,
    }
    other_vendor = "vendor_b" if expected_vendor == "vendor_a" else "vendor_a"

    transaction = postgres_session.get(Transaction, transaction_id)
    assert transaction is not None
    assert result["structuredContent"]["vendor_code"] == expected_vendor
    assert transaction.vendor_code == expected_vendor
    assert submitted[expected_vendor] == [transaction_id]
    assert submitted[other_vendor] == []


def test_status_lookup_follows_persisted_vendor_when_vendor_code_is_injected(
    postgres_session: Session,
    created_transaction_ids: list[UUID],
    vendor_ledger_calls: VendorLedgerCalls,
):
    first = call_mcp_tool(
        "execute_transaction",
        execute_arguments(f"mcp-boundary-status-{uuid4()}"),
    )
    transaction_id = record_result_id(first, created_transaction_ids)
    assert vendor_ledger_calls.a_submits == [transaction_id]

    transaction = postgres_session.get(Transaction, transaction_id)
    assert transaction is not None
    transaction.state = TransactionState.UNKNOWN
    transaction.error_message = None
    transaction.raw_vendor_response = None
    transaction.vendor_reference = None
    postgres_session.add(transaction)
    postgres_session.commit()

    status = call_mcp_tool(
        "get_transaction_status",
        {"transaction_id": str(transaction_id), "vendor_code": "vendor_b"},
    )

    assert vendor_ledger_calls.b_queries == []
    assert vendor_ledger_calls.b_submits == []
    assert vendor_ledger_calls.a_submits == [transaction_id]
    if status.get("isError") is True:
        # A stricter SDK may reject the undeclared field; the row must be untouched.
        postgres_session.refresh(transaction)
        assert transaction.state == TransactionState.UNKNOWN
        assert vendor_ledger_calls.a_queries == []
        return

    assert status["structuredContent"]["status"] == "success"
    assert (
        status["structuredContent"]["vendor_reference"] == f"vendor_a-{transaction_id}"
    )
    assert vendor_ledger_calls.a_queries == [transaction_id]


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param({"transaction_id": "not-a-uuid"}, id="malformed-uuid"),
        pytest.param({"transaction_id": ""}, id="empty"),
        pytest.param({}, id="missing"),
    ],
)
def test_status_rejects_invalid_transaction_id_without_vendor_calls(
    arguments: dict[str, object],
    vendor_ledger_calls: VendorLedgerCalls,
):
    result = call_mcp_tool("get_transaction_status", arguments)

    assert result["isError"] is True
    assert not vendor_ledger_calls.any_vendor_call


def test_status_for_unknown_transaction_is_an_error_without_vendor_calls(
    postgres_session: Session,
    vendor_ledger_calls: VendorLedgerCalls,
):
    unknown_id = uuid4()

    result = call_mcp_tool(
        "get_transaction_status",
        {"transaction_id": str(unknown_id)},
    )

    assert result["isError"] is True
    assert "does not exist" in result["content"][0]["text"]
    assert postgres_session.get(Transaction, unknown_id) is None
    assert not vendor_ledger_calls.any_vendor_call


@pytest.mark.parametrize("missing_field", ["service_type", "product_type", "network"])
def test_find_capabilities_requires_every_declared_input(missing_field: str):
    arguments = {"service_type": "airtime", "product_type": "airtime", "network": "MTN"}
    del arguments[missing_field]

    result = call_mcp_tool("find_transaction_capabilities", arguments)

    assert result["isError"] is True


def test_find_capabilities_ignores_injected_vendor_filter():
    arguments = {"service_type": "airtime", "product_type": "airtime", "network": "MTN"}

    baseline = call_mcp_tool("find_transaction_capabilities", arguments)
    injected = call_mcp_tool(
        "find_transaction_capabilities",
        {**arguments, "vendor_code": "vendor_b"},
    )

    def by_vendor(result: dict[str, Any]) -> list[dict[str, Any]]:
        return sorted(
            result["structuredContent"]["capabilities"],
            key=lambda capability: capability["vendor_code"],
        )

    assert baseline.get("isError") is not True
    assert injected.get("isError") is True or by_vendor(injected) == by_vendor(baseline)


@pytest.mark.parametrize(
    "tool_name",
    [
        "authenticate",
        "execute_vendor_transaction",
        "query_vendor_transaction",
        "call_vendor_api",
    ],
)
def test_internal_vendor_operations_cannot_be_called_as_tools(
    tool_name: str,
    postgres_session: Session,
    vendor_ledger_calls: VendorLedgerCalls,
):
    key = f"mcp-boundary-internal-{uuid4()}"

    result = call_mcp_tool(tool_name, execute_arguments(key))

    assert result["isError"] is True
    assert transactions_with_key(postgres_session, key) == 0
    assert not vendor_ledger_calls.any_vendor_call
