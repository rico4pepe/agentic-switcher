"""Protocol-level integration tests for MCP transaction execution."""

from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from apps.api.app.database import SessionLocal, engine
from apps.api.app.domain.transaction import Transaction
from apps.api.app.main import app
from capabilities.domain import Capability, CapabilityOperation, WorkflowStep
from capabilities.registry import CapabilityRegistry
from vendors.base.models import (
    AuthenticationRequest,
    TransactionExecutionRequest,
    VendorTransactionResult,
    VendorTransactionStatus,
)
from vendors.vendor_a import VendorAAdapter
from vendors.vendor_a.operation_ledger import (
    PostgresVendorAOperationLedger,
    VendorAOperationRecord,
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
def created_transaction_ids(
    postgres_session: Session,
) -> Iterator[list[UUID]]:
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
                delete(Transaction).where(Transaction.id.in_(transaction_ids))
            )
            postgres_session.commit()


@pytest.fixture
def vendor_submission_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> list[UUID]:
    submitted_ids: list[UUID] = []
    original_submit = PostgresVendorAOperationLedger.submit

    def counted_submit(
        ledger: PostgresVendorAOperationLedger,
        request: TransactionExecutionRequest,
    ) -> VendorTransactionResult:
        submitted_ids.append(request.transaction_id)
        return original_submit(ledger, request)

    monkeypatch.setattr(
        PostgresVendorAOperationLedger,
        "submit",
        counted_submit,
    )
    return submitted_ids


def call_mcp_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
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
    return response.json()["result"]


def execute_arguments(
    idempotency_key: str,
    *,
    amount: str = "5000.00",
) -> dict[str, object]:
    return {
        "service_type": "airtime",
        "product_type": "airtime",
        "network": "MTN",
        "beneficiary": "08030000000",
        "amount": amount,
        "idempotency_key": idempotency_key,
    }


def record_result_id(
    result: dict[str, object],
    transaction_ids: list[UUID],
) -> UUID:
    result_body = result["structuredContent"]
    transaction_id = UUID(str(result_body["transaction_id"]))
    transaction_ids.append(transaction_id)
    return transaction_id


def test_mcp_success_executes_and_persists_one_canonical_vendor_operation(
    postgres_session: Session,
    created_transaction_ids: list[UUID],
    vendor_submission_ids: list[UUID],
):
    result = call_mcp_tool(
        "execute_transaction",
        execute_arguments("mcp-success-001"),
    )
    transaction_id = record_result_id(result, created_transaction_ids)
    body = result["structuredContent"]

    transaction = postgres_session.get(Transaction, transaction_id)
    operation = postgres_session.get(VendorAOperationRecord, transaction_id)

    assert result.get("isError") is not True
    assert body["transaction_id"] == str(transaction_id)
    assert body["status"] == "success"
    assert body["service_type"] == "airtime"
    assert body["vendor_reference"] == f"vendor_a-{transaction_id}"
    assert Decimal(body["amount"]) == Decimal("5000.00")
    assert transaction is not None
    assert transaction.state.value == "success"
    assert operation is not None
    assert vendor_submission_ids == [transaction_id]


def test_mcp_same_key_replay_reuses_transaction_without_another_submission(
    postgres_session: Session,
    created_transaction_ids: list[UUID],
    vendor_submission_ids: list[UUID],
):
    arguments = execute_arguments("mcp-replay-001")
    first = call_mcp_tool("execute_transaction", arguments)
    second = call_mcp_tool("execute_transaction", arguments)
    first_id = record_result_id(first, created_transaction_ids)

    assert second["structuredContent"]["transaction_id"] == str(first_id)
    assert postgres_session.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.idempotency_key == "mcp-replay-001")
    ) == 1
    assert vendor_submission_ids == [first_id]


def test_mcp_same_key_different_inputs_returns_conflict_without_submission(
    created_transaction_ids: list[UUID],
    vendor_submission_ids: list[UUID],
):
    first = call_mcp_tool(
        "execute_transaction",
        execute_arguments("mcp-conflict-001"),
    )
    transaction_id = record_result_id(first, created_transaction_ids)
    conflict = call_mcp_tool(
        "execute_transaction",
        execute_arguments("mcp-conflict-001", amount="7000.00"),
    )

    assert conflict["isError"] is True
    assert "Idempotency key is already associated" in conflict["content"][0]["text"]
    assert vendor_submission_ids == [transaction_id]


def test_mcp_rejects_matching_capability_without_execute_operation(
    postgres_session: Session,
    vendor_submission_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
):
    def find_non_executable_capability(
        _registry: CapabilityRegistry,
        *,
        service_type: str,
        product_type: str,
        network: str | None,
    ) -> tuple[Capability, ...]:
        assert (service_type, product_type, network) == (
            "airtime",
            "airtime",
            "MTN",
        )
        return (
            Capability(
                vendor_code=VendorAAdapter.VENDOR_CODE,
                service_type=service_type,
                product_type=product_type,
                network=network,
                supported_operations=frozenset(
                    {CapabilityOperation.AUTHENTICATE}
                ),
                workflow=(WorkflowStep(CapabilityOperation.AUTHENTICATE),),
            ),
        )

    monkeypatch.setattr(CapabilityRegistry, "find", find_non_executable_capability)
    idempotency_key = "mcp-no-execute-capability-001"

    result = call_mcp_tool(
        "execute_transaction",
        execute_arguments(idempotency_key),
    )

    assert result["isError"] is True
    assert "Unsupported transaction capability" in result["content"][0]["text"]
    assert postgres_session.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.idempotency_key == idempotency_key)
    ) == 0
    assert vendor_submission_ids == []


def test_mcp_different_keys_create_independent_vendor_operations(
    created_transaction_ids: list[UUID],
    vendor_submission_ids: list[UUID],
):
    first = call_mcp_tool(
        "execute_transaction",
        execute_arguments("mcp-independent-001"),
    )
    second = call_mcp_tool(
        "execute_transaction",
        execute_arguments("mcp-independent-002"),
    )
    first_id = record_result_id(first, created_transaction_ids)
    second_id = record_result_id(second, created_transaction_ids)

    assert first_id != second_id
    assert vendor_submission_ids == [first_id, second_id]


def test_mcp_unknown_replay_does_not_resubmit(
    created_transaction_ids: list[UUID],
    vendor_submission_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
):
    def create_unknown_adapter(
        vendor_code: str,
        settings: Settings,
    ) -> VendorAAdapter:
        assert vendor_code == VendorAAdapter.VENDOR_CODE
        adapter = VendorAAdapter(
            PostgresVendorAOperationLedger(
                SessionLocal,
                submission_status=VendorTransactionStatus.UNKNOWN,
            )
        )
        adapter.authenticate(
            AuthenticationRequest({"api_key": settings.vendor_a_api_key})
        )
        return adapter

    monkeypatch.setattr(
        "apps.api.app.mcp_server.app.create_authenticated_adapter",
        create_unknown_adapter,
    )
    arguments = execute_arguments("mcp-unknown-001")
    first = call_mcp_tool("execute_transaction", arguments)
    transaction_id = record_result_id(first, created_transaction_ids)
    second = call_mcp_tool("execute_transaction", arguments)

    assert first["structuredContent"]["status"] == "unknown"
    assert second["structuredContent"]["status"] == "unknown"
    assert second["structuredContent"]["transaction_id"] == str(transaction_id)
    assert vendor_submission_ids == [transaction_id]


def test_mcp_execute_schema_exposes_only_business_inputs():
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                },
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Method": "tools/list",
                "Mcp-Protocol-Version": "2026-07-28",
            },
        )

    assert response.status_code == 200, response.text
    tools = response.json()["result"]["tools"]
    tool = next(item for item in tools if item["name"] == "execute_transaction")
    properties = tool["inputSchema"]["properties"]
    assert set(properties) == {
        "service_type",
        "product_type",
        "network",
        "beneficiary",
        "amount",
        "idempotency_key",
    }
    assert set(tool["inputSchema"]["required"]) == {
        "service_type",
        "product_type",
        "beneficiary",
        "amount",
        "idempotency_key",
    }
    schema_text = str(tool["inputSchema"]).lower()
    assert not any(
        forbidden in schema_text
        for forbidden in (
            "vendor_code",
            "api_key",
            "credential",
            "secret",
            "url",
            "adapter",
            "raw_request",
            "raw_response",
        )
    )
