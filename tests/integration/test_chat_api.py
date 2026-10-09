"""HTTP integration tests for the /api/chat conversation boundary.

These tests exercise the real FastAPI application (with its lifespan-managed
MCP server) and the existing RequestUnderstanding -> AgentRuntime ->
TransactionOrchestrator -> MCP business-tool path. They assert the browser can
only submit a natural-language message and receive the authoritative result
plus its deterministic explanation.
"""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from agent.orchestrator.service import MCPClientBusinessTools
from agent.request_understanding import RequestUnderstanding
from agent.runtime.service import AgentRuntime
from apps.api.app.database import SessionLocal
from apps.api.app.domain.transaction import Transaction
from apps.api.app.main import app
from switcher.demo.scenarios import (
    DemoScenarioName,
    get_demo_scenario,
    set_demo_scenario,
)
from vendors.vendor_a.operation_ledger import VendorAOperationRecord
from vendors.vendor_b.operation_ledger import VendorBOperationRecord


VALID_MESSAGE = "Buy ₦5,000 MTN airtime for 08030000001."

RESULT_FIELDS = {
    "transaction_id",
    "status",
    "service_type",
    "product_type",
    "network",
    "beneficiary",
    "amount",
    "vendor_code",
    "vendor_reference",
    "action",
    "reason",
    "message",
    "planner_candidate_vendor",
}


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _delete_transaction(transaction_id: UUID) -> None:
    with SessionLocal() as session:
        session.execute(
            delete(VendorAOperationRecord).where(
                VendorAOperationRecord.transaction_id == transaction_id
            )
        )
        session.execute(
            delete(VendorBOperationRecord).where(
                VendorBOperationRecord.transaction_id == transaction_id
            )
        )
        session.execute(
            delete(Transaction).where(Transaction.id == transaction_id)
        )
        session.commit()


def test_valid_message_returns_structured_response_and_uses_runtime(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    recorded: list[object] = []
    original_execute = AgentRuntime.execute

    async def recording_execute(self, request):
        recorded.append(request)
        return await original_execute(self, request)

    monkeypatch.setattr(AgentRuntime, "execute", recording_execute)

    response = client.post("/api/chat", json={"message": VALID_MESSAGE})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESULT_FIELDS | {"explanation"}
    assert body["status"] == "success"
    assert body["action"] == "allow"
    assert body["vendor_code"] == "vendor_a"
    assert body["planner_candidate_vendor"] == "vendor_a"
    assert body["transaction_id"] is not None
    assert "completed successfully" in body["explanation"]
    assert "Vendor A" in body["explanation"]

    assert len(recorded) == 1
    assert recorded[0] == RequestUnderstanding().parse(VALID_MESSAGE)

    transaction_id = UUID(body["transaction_id"])
    try:
        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
            operation = session.get(VendorAOperationRecord, transaction_id)
        assert transaction is not None
        assert transaction.state.value == "success"
        assert operation is not None
    finally:
        _delete_transaction(transaction_id)


def test_policy_denial_is_reported_without_vendor_submission(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    set_demo_scenario(DemoScenarioName.POLICY_DENIED)

    submissions: list[str] = []

    def record_submission(*_args, **_kwargs):
        submissions.append("submitted")

    monkeypatch.setattr(
        "vendors.vendor_a.operation_ledger.PostgresVendorAOperationLedger.submit",
        record_submission,
    )
    monkeypatch.setattr(
        "vendors.vendor_b.operation_ledger.PostgresVendorBOperationLedger.submit",
        record_submission,
    )

    response = client.post("/api/chat", json={"message": VALID_MESSAGE})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "denied"
    assert body["action"] == "deny"
    assert body["reason"] == "Insufficient balance"
    assert body["transaction_id"] is None
    assert body["vendor_code"] is None
    assert body["vendor_reference"] is None
    assert "Insufficient balance" in body["explanation"]
    assert submissions == []


def test_vendor_a_unavailable_routes_through_switcher_to_vendor_b(
    client: TestClient,
):
    set_demo_scenario(DemoScenarioName.VENDOR_A_UNAVAILABLE)

    response = client.post("/api/chat", json={"message": VALID_MESSAGE})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["action"] == "allow"
    assert body["vendor_code"] == "vendor_b"
    assert body["planner_candidate_vendor"] == "vendor_a"
    assert "Vendor B" in body["explanation"]
    assert get_demo_scenario() == DemoScenarioName.VENDOR_A_UNAVAILABLE

    transaction_id = UUID(body["transaction_id"])
    try:
        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
            operation = session.get(VendorBOperationRecord, transaction_id)
        assert transaction is not None
        assert transaction.vendor_code == "vendor_b"
        assert transaction.state.value == "success"
        assert operation is not None
    finally:
        _delete_transaction(transaction_id)


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"message": ""}, 422),
        ({"message": "   "}, 422),
        ({"message": "hello there"}, 400),
        ({"message": "Buy airtime for 08030000001."}, 400),
        ({"message": "Buy ₦5,000 data MTN for 08030000001."}, 400),
        ({"message": VALID_MESSAGE, "vendor_code": "vendor_b"}, 422),
        ({"message": VALID_MESSAGE, "idempotency_key": "caller-key"}, 422),
    ],
)
def test_invalid_or_incomplete_input_returns_client_error_without_executing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    expected_status: int,
):
    executed: list[object] = []

    async def fail_execute(self, request):
        executed.append(request)
        raise AssertionError("Invalid input must not reach the runtime")

    monkeypatch.setattr(AgentRuntime, "execute", fail_execute)

    response = client.post("/api/chat", json=payload)

    assert response.status_code == expected_status
    assert executed == []


def test_timeout_unknown_outcome_is_preserved_without_blind_retry(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    set_demo_scenario(DemoScenarioName.TIMEOUT)

    execution_calls: list[dict[str, object]] = []
    original_execute_transaction = MCPClientBusinessTools.execute_transaction

    async def recording_execute_transaction(self, **kwargs):
        execution_calls.append(kwargs)
        return await original_execute_transaction(self, **kwargs)

    monkeypatch.setattr(
        MCPClientBusinessTools,
        "execute_transaction",
        recording_execute_transaction,
    )

    response = client.post("/api/chat", json={"message": VALID_MESSAGE})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unknown"
    assert body["action"] == "allow"
    assert "could not be confirmed" in body["explanation"]
    assert "retry" not in body["explanation"].lower()
    assert len(execution_calls) == 1

    transaction_id = UUID(body["transaction_id"])
    try:
        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
        assert transaction is not None
        assert transaction.state.value == "unknown"
    finally:
        _delete_transaction(transaction_id)


def test_existing_health_and_demo_endpoints_remain_compatible(
    client: TestClient,
):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    scenarios = client.get("/api/demo/scenarios")
    assert scenarios.status_code == 200
    assert scenarios.json()["current"]["scenario"] == DemoScenarioName.NORMAL.value
