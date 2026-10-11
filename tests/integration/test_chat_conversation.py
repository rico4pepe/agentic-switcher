"""HTTP integration tests for the multi-turn airtime conversation boundary.

These tests exercise the real FastAPI application (with its lifespan-managed
MCP server) and the existing RequestUnderstanding -> AgentRuntime ->
TransactionOrchestrator -> MCP business-tool path. Conversation mode collects
missing fields, requires explicit confirmation, and reuses the single existing
execution path.
"""

import asyncio
from collections.abc import Iterator
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from agent.orchestrator.service import MCPBusinessToolError, MCPClientBusinessTools
from agent.runtime.service import AgentRuntime
from apps.api.app import conversations as conversations_module
from apps.api.app.conversations import ConversationStore, reset_conversations
from apps.api.app.database import SessionLocal
from apps.api.app.domain.transaction import Transaction
from apps.api.app.main import app, lifespan
from switcher.demo.scenarios import DemoScenarioName, set_demo_scenario
from vendors.vendor_a.operation_ledger import VendorAOperationRecord
from vendors.vendor_b.operation_ledger import VendorBOperationRecord


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


@pytest.fixture(autouse=True)
def _isolate_conversations() -> Iterator[None]:
    reset_conversations()
    yield
    reset_conversations()


@pytest.fixture
def client() -> Iterator[TestClient]:
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


def conversation_turn(
    client: TestClient,
    message: str,
    conversation_id: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {"message": message, "mode": "conversation"}
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def start_conversation(client: TestClient, message: str) -> str:
    body = conversation_turn(client, message, None)
    return str(body["conversation_id"])


def _record_executions(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    original = MCPClientBusinessTools.execute_transaction

    async def recording(self, **kwargs):
        calls.append(kwargs)
        return await original(self, **kwargs)

    monkeypatch.setattr(
        MCPClientBusinessTools, "execute_transaction", recording
    )
    return calls


def test_legacy_execute_mode_is_unchanged(client: TestClient):
    response = client.post(
        "/api/chat",
        json={"message": "Buy ₦5,000 MTN airtime for 08030000001."},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == RESULT_FIELDS | {"explanation"}
    assert body["status"] == "success"

    _delete_transaction(UUID(str(body["transaction_id"])))


def test_legacy_mode_rejects_conversation_id(client: TestClient):
    response = client.post(
        "/api/chat",
        json={
            "message": "Buy ₦5,000 MTN airtime for 08030000001.",
            "conversation_id": "abc",
        },
    )

    assert response.status_code == 422


def test_conversation_collects_fields_and_requires_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    executions: list[object] = []
    original_execute = AgentRuntime.execute

    async def recording_execute(self, request):
        executions.append(request)
        return await original_execute(self, request)

    monkeypatch.setattr(AgentRuntime, "execute", recording_execute)

    body = conversation_turn(client, "Buy ₦5,000 airtime.", None)
    conversation_id = str(body["conversation_id"])
    assert body["step"] == "clarify"
    assert body["result"] is None
    assert set(body["missing_fields"]) == {"network", "beneficiary"}
    assert body["draft"]["amount"] == "5000.00"
    assert body["draft"]["service_type"] == "airtime"

    body = conversation_turn(client, "MTN", conversation_id)
    assert body["step"] == "clarify"
    assert body["missing_fields"] == ["beneficiary"]
    assert body["draft"]["network"] == "MTN"
    assert body["result"] is None

    body = conversation_turn(client, "08030000001", conversation_id)
    assert body["step"] == "confirm"
    assert body["result"] is None
    assert "₦5,000" in body["prompt"]
    assert "08030000001" in body["prompt"]

    # Collection and confirmation must not execute anything.
    assert executions == []

    completed = conversation_turn(client, "confirm", conversation_id)
    assert completed["step"] == "complete"
    result = completed["result"]
    assert result["status"] == "success"
    assert result["vendor_code"] == "vendor_a"
    assert len(executions) == 1

    transaction_id = UUID(str(result["transaction_id"]))
    try:
        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
        assert transaction is not None
        assert transaction.state.value == "success"
    finally:
        _delete_transaction(transaction_id)


def test_repeated_confirmation_replays_without_second_execution(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    calls = _record_executions(monkeypatch)

    body = conversation_turn(
        client, "Buy ₦5,000 MTN airtime for 08030000001.", None
    )
    conversation_id = str(body["conversation_id"])
    assert body["step"] == "confirm"

    first = conversation_turn(client, "confirm", conversation_id)
    second = conversation_turn(client, "yes", conversation_id)

    assert first["step"] == "complete"
    assert second["step"] == "complete"
    assert first["result"]["transaction_id"] == second["result"]["transaction_id"]
    assert len(calls) == 1

    _delete_transaction(UUID(str(first["result"]["transaction_id"])))


def test_different_request_on_completed_conversation_is_rejected(
    client: TestClient,
):
    body = conversation_turn(
        client, "Buy ₦5,000 MTN airtime for 08030000001.", None
    )
    conversation_id = str(body["conversation_id"])

    completed = conversation_turn(client, "confirm", conversation_id)
    transaction_id = UUID(str(completed["result"]["transaction_id"]))

    try:
        conflict = client.post(
            "/api/chat",
            json={
                "message": "Buy ₦9,000 airtime.",
                "mode": "conversation",
                "conversation_id": conversation_id,
            },
        )
        assert conflict.status_code == 409
    finally:
        _delete_transaction(transaction_id)


def test_cancellation_is_terminal_and_prevents_execution(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    calls = _record_executions(monkeypatch)

    body = conversation_turn(
        client, "Buy ₦5,000 MTN airtime for 08030000001.", None
    )
    conversation_id = str(body["conversation_id"])

    cancelled = conversation_turn(client, "cancel", conversation_id)
    assert cancelled["step"] == "cancelled"
    assert cancelled["result"] is None
    assert calls == []

    delayed = client.post(
        "/api/chat",
        json={
            "message": "confirm",
            "mode": "conversation",
            "conversation_id": conversation_id,
        },
    )
    assert delayed.status_code == 409
    assert calls == []


def test_unknown_conversation_id_returns_not_found(client: TestClient):
    response = client.post(
        "/api/chat",
        json={
            "message": "confirm",
            "mode": "conversation",
            "conversation_id": "does-not-exist",
        },
    )

    assert response.status_code == 404


def test_policy_denial_is_reported_after_confirmation(
    client: TestClient,
):
    set_demo_scenario(DemoScenarioName.POLICY_DENIED)

    body = conversation_turn(
        client, "Buy ₦5,000 MTN airtime for 08030000001.", None
    )
    conversation_id = str(body["conversation_id"])
    assert body["step"] == "confirm"

    completed = conversation_turn(client, "confirm", conversation_id)

    result = completed["result"]
    assert result["status"] == "denied"
    assert result["action"] == "deny"
    assert result["transaction_id"] is None
    assert result["vendor_code"] is None
    assert "Insufficient balance" in result["explanation"]


def test_vendor_fallback_is_selected_after_confirmation(
    client: TestClient,
):
    set_demo_scenario(DemoScenarioName.VENDOR_A_UNAVAILABLE)

    body = conversation_turn(
        client, "Buy ₦5,000 MTN airtime for 08030000001.", None
    )
    conversation_id = str(body["conversation_id"])

    completed = conversation_turn(client, "confirm", conversation_id)
    result = completed["result"]
    assert result["status"] == "success"
    assert result["vendor_code"] == "vendor_b"

    transaction_id = UUID(str(result["transaction_id"]))
    try:
        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
        assert transaction is not None
        assert transaction.vendor_code == "vendor_b"
    finally:
        _delete_transaction(transaction_id)


def test_timeout_unknown_is_preserved_without_retry(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    set_demo_scenario(DemoScenarioName.TIMEOUT)
    calls = _record_executions(monkeypatch)

    body = conversation_turn(
        client, "Buy ₦5,000 MTN airtime for 08030000001.", None
    )
    conversation_id = str(body["conversation_id"])

    completed = conversation_turn(client, "confirm", conversation_id)
    result = completed["result"]

    assert result["status"] == "unknown"
    assert result["transaction_id"] is not None
    assert "could not be confirmed" in result["explanation"]
    assert len(calls) == 1

    transaction_id = UUID(str(result["transaction_id"]))
    try:
        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
        assert transaction is not None
        assert transaction.state.value == "unknown"
    finally:
        _delete_transaction(transaction_id)


def test_mcp_error_maps_to_unknown_without_retry(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    attempts: list[dict[str, object]] = []

    async def failing(self, **kwargs):
        attempts.append(kwargs)
        raise MCPBusinessToolError("MCP tool execute_transaction returned an error")

    monkeypatch.setattr(
        MCPClientBusinessTools, "execute_transaction", failing
    )

    body = conversation_turn(
        client, "Buy ₦5,000 MTN airtime for 08030000001.", None
    )
    conversation_id = str(body["conversation_id"])

    completed = conversation_turn(client, "confirm", conversation_id)
    result = completed["result"]

    assert completed["step"] == "complete"
    assert result["status"] == "unknown"
    assert result["transaction_id"] is None
    assert result["beneficiary"] == "08030000001"
    assert len(attempts) == 1

    # A repeated confirmation replays the cached unknown result; no retry.
    replay = conversation_turn(client, "confirm", conversation_id)
    assert replay["result"]["status"] == "unknown"
    assert len(attempts) == 1


def test_new_conversation_uses_a_fresh_identifier(client: TestClient):
    first = start_conversation(client, "Buy ₦5,000 airtime.")
    second = start_conversation(client, "Buy ₦7,000 airtime.")

    assert first != second

    for conversation_id in (first, second):
        response = client.post(
            "/api/chat",
            json={
                "message": "cancel",
                "mode": "conversation",
                "conversation_id": conversation_id,
            },
        )
        assert response.status_code == 200


def test_concurrent_confirmations_execute_at_most_once(monkeypatch: pytest.MonkeyPatch):
    calls = _record_executions(monkeypatch)

    async def journey() -> list[httpx.Response]:
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://localhost"
            ) as async_client:
                started = await async_client.post(
                    "/api/chat",
                    json={
                        "message": "Buy ₦5,000 MTN airtime for 08030000001.",
                        "mode": "conversation",
                    },
                )
                assert started.status_code == 200, started.text
                conversation_id = started.json()["conversation_id"]
                assert started.json()["step"] == "confirm"

                payload = {
                    "message": "confirm",
                    "mode": "conversation",
                    "conversation_id": conversation_id,
                }
                return await asyncio.gather(
                    async_client.post("/api/chat", json=payload),
                    async_client.post("/api/chat", json=payload),
                )

    responses = asyncio.run(journey())

    assert [response.status_code for response in responses] == [200, 200]
    bodies = [response.json() for response in responses]
    assert all(body["step"] == "complete" for body in bodies)

    transaction_ids = {str(body["result"]["transaction_id"]) for body in bodies}
    assert len(transaction_ids) == 1
    assert len(calls) == 1

    for transaction_id in transaction_ids:
        _delete_transaction(UUID(transaction_id))


def test_unexpected_execution_error_terminates_as_unknown(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    attempts: list[dict[str, object]] = []

    async def exploding(self, **kwargs):
        attempts.append(kwargs)
        raise RuntimeError("unexpected internal failure")

    monkeypatch.setattr(MCPClientBusinessTools, "execute_transaction", exploding)

    body = conversation_turn(
        client, "Buy ₦5,000 MTN airtime for 08030000001.", None
    )
    conversation_id = str(body["conversation_id"])

    completed = conversation_turn(client, "confirm", conversation_id)
    assert completed["step"] == "complete"
    assert completed["result"]["status"] == "unknown"
    assert completed["result"]["transaction_id"] is None
    assert len(attempts) == 1

    # The conversation is terminal; a repeated confirmation replays and never
    # retries the uncertain submission.
    replay = conversation_turn(client, "confirm", conversation_id)
    assert replay["result"]["status"] == "unknown"
    assert len(attempts) == 1


def test_error_after_persistence_reports_unknown_without_retry(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    persisted_ids: list[str] = []
    original = MCPClientBusinessTools.execute_transaction

    async def persist_then_fail(self, **kwargs):
        result = await original(self, **kwargs)
        persisted_ids.append(str(result["transaction_id"]))
        raise MCPBusinessToolError("response lost after persistence")

    monkeypatch.setattr(
        MCPClientBusinessTools, "execute_transaction", persist_then_fail
    )

    body = conversation_turn(
        client, "Buy ₦5,000 MTN airtime for 08030000001.", None
    )
    conversation_id = str(body["conversation_id"])

    completed = conversation_turn(client, "confirm", conversation_id)
    assert completed["result"]["status"] == "unknown"
    # The transaction was persisted, but the MCP error contract does not return
    # its identity, so the conversation cannot know or fabricate it.
    assert completed["result"]["transaction_id"] is None
    assert len(persisted_ids) == 1

    replay = conversation_turn(client, "confirm", conversation_id)
    assert replay["result"]["status"] == "unknown"
    assert len(persisted_ids) == 1

    for transaction_id in persisted_ids:
        _delete_transaction(UUID(transaction_id))


def test_conversation_capacity_exhaustion_returns_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        conversations_module,
        "default_store",
        ConversationStore(max_conversations=1),
    )

    first = client.post(
        "/api/chat",
        json={"message": "Buy ₦5,000 airtime.", "mode": "conversation"},
    )
    assert first.status_code == 200
    assert first.json()["step"] == "clarify"

    second = client.post(
        "/api/chat",
        json={"message": "Buy ₦9,000 airtime.", "mode": "conversation"},
    )
    assert second.status_code == 503
    assert "capacity" in second.json()["detail"].lower()
