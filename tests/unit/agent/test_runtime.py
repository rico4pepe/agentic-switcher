"""Tests for the application-level agent runtime boundary."""

import asyncio
from decimal import Decimal
from typing import Mapping
from uuid import UUID

import pytest
from pydantic import ValidationError

from agent.orchestrator.service import OrchestrationRequest
from agent.runtime.service import (
    AgentRequest,
    AgentResult,
    AgentRuntime,
    InvalidAgentResultError,
)


class FakeOrchestrator:
    def __init__(self, result: Mapping[str, object]) -> None:
        self.result = result
        self.requests: list[OrchestrationRequest] = []

    async def execute(
        self,
        request: OrchestrationRequest,
    ) -> Mapping[str, object]:
        self.requests.append(request)
        return self.result


def agent_request(**overrides: object) -> AgentRequest:
    values: dict[str, object] = {
        "intent": "airtime_purchase",
        "service_type": "airtime",
        "product_type": "airtime",
        "network": "MTN",
        "beneficiary": "08030000000",
        "amount": Decimal("5000.00"),
    }
    values.update(overrides)
    return AgentRequest(**values)


def transaction_result(*, status: str = "success") -> dict[str, object]:
    return {
        "transaction_id": "8e4cb8cf-79da-49ab-aa35-865d1105b45e",
        "status": status,
        "service_type": "airtime",
        "product_type": "airtime",
        "network": "MTN",
        "beneficiary": "08030000000",
        "amount": "5000.00",
        "vendor_reference": "vendor-a-reference",
        "message": f"Transaction {status}",
    }


def test_successful_request_reaches_orchestrator_and_returns_success():
    orchestrator = FakeOrchestrator(transaction_result())
    runtime = AgentRuntime(orchestrator)  # type: ignore[arg-type]

    result = asyncio.run(runtime.execute(agent_request()))

    assert isinstance(result, AgentResult)
    assert result.status == "success"
    assert result.transaction_id == UUID("8e4cb8cf-79da-49ab-aa35-865d1105b45e")
    assert len(orchestrator.requests) == 1


@pytest.mark.parametrize("status", ["failed", "unknown"])
def test_runtime_preserves_failed_and_unknown_status(status: str):
    orchestrator = FakeOrchestrator(transaction_result(status=status))
    runtime = AgentRuntime(orchestrator)  # type: ignore[arg-type]

    result = asyncio.run(runtime.execute(agent_request()))

    assert result.status == status
    assert result.message == f"Transaction {status}"


def test_runtime_preserves_submitted_status():
    orchestrator = FakeOrchestrator(transaction_result(status="submitted"))
    runtime = AgentRuntime(orchestrator)  # type: ignore[arg-type]

    result = asyncio.run(runtime.execute(agent_request()))

    assert result.status == "submitted"


def test_runtime_passes_original_structured_business_fields_unchanged():
    orchestrator = FakeOrchestrator(transaction_result())
    runtime = AgentRuntime(orchestrator)  # type: ignore[arg-type]
    request = agent_request(
        intent="customer_airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network=None,
        beneficiary="08031112222",
        amount=Decimal("1250.75"),
    )

    asyncio.run(runtime.execute(request))

    assert orchestrator.requests == [
        OrchestrationRequest(
            intent="customer_airtime_purchase",
            service_type="airtime",
            product_type="airtime",
            network=None,
            beneficiary="08031112222",
            amount=Decimal("1250.75"),
        )
    ]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("vendor_credentials", {"api_key": "secret"}),
        ("vendor_url", "https://vendor.invalid"),
        ("http_method", "POST"),
        ("api_endpoint", "/transactions"),
        ("adapter_name", "vendor_a"),
        ("raw_vendor_request", {"anything": "goes"}),
        ("idempotency_key", "caller-key"),
        ("tool_name", "execute_transaction"),
    ],
)
def test_request_rejects_non_business_fields(field_name: str, value: object):
    values = agent_request().model_dump()
    values[field_name] = value

    with pytest.raises(ValidationError):
        AgentRequest.model_validate(values)


def test_runtime_does_not_accept_or_generate_idempotency_key():
    assert "idempotency_key" not in AgentRequest.__annotations__
    orchestrator = FakeOrchestrator(transaction_result())
    runtime = AgentRuntime(orchestrator)  # type: ignore[arg-type]

    asyncio.run(runtime.execute(agent_request()))

    assert not hasattr(orchestrator.requests[0], "idempotency_key")


@pytest.mark.parametrize(
    "result",
    [
        {},
        {**transaction_result(), "status": "completed"},
        {**transaction_result(), "status": "unknown", "amount": "not-a-number"},
    ],
)
def test_malformed_orchestration_result_is_rejected_not_promoted_to_success(
    result: Mapping[str, object],
):
    orchestrator = FakeOrchestrator(result)
    runtime = AgentRuntime(orchestrator)  # type: ignore[arg-type]

    with pytest.raises(InvalidAgentResultError):
        asyncio.run(runtime.execute(agent_request()))


def test_runtime_module_uses_only_the_injected_orchestrator():
    orchestrator = FakeOrchestrator(transaction_result())
    runtime = AgentRuntime(orchestrator)  # type: ignore[arg-type]

    asyncio.run(runtime.execute(agent_request()))

    assert len(orchestrator.requests) == 1
    assert set(AgentRequest.__annotations__) == {
        "intent",
        "service_type",
        "product_type",
        "network",
        "beneficiary",
        "amount",
    }