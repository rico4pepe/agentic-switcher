"""Milestone 2: the planner's advisory candidate vendor reaches AgentResult.

The planner proposes a candidate vendor; the deterministic Switcher decides the
vendor that actually executes. These tests prove the proposal is exposed on the
existing AgentResult without granting it any routing authority.
"""

import asyncio
from collections.abc import Mapping
from decimal import Decimal

from agent.orchestrator.service import TransactionOrchestrator
from agent.runtime.service import AgentRequest, AgentResult, AgentRuntime
from switcher.routing import reset_vendor_availability, set_vendor_availability
from tests.unit.agent.test_orchestrator import (
    FakePlanner,
    capability_dto,
    valid_plan,
)


class RecordingMCPBusinessTools:
    """Return an execution result that echoes the vendor the Switcher selected."""

    def __init__(self) -> None:
        self.execution_calls: list[dict[str, object]] = []

    async def find_transaction_capabilities(
        self,
        *,
        service_type: str,
        product_type: str,
        network: str | None,
    ) -> Mapping[str, object]:
        return {
            "capabilities": [
                capability_dto("vendor_a"),
                capability_dto("vendor_b"),
            ]
        }

    async def execute_transaction(
        self,
        *,
        service_type: str,
        product_type: str,
        network: str | None,
        beneficiary: str,
        amount: Decimal,
        vendor_code: str,
        idempotency_key: str,
    ) -> Mapping[str, object]:
        self.execution_calls.append(
            {
                "service_type": service_type,
                "product_type": product_type,
                "network": network,
                "beneficiary": beneficiary,
                "amount": amount,
                "vendor_code": vendor_code,
                "idempotency_key": idempotency_key,
            }
        )
        return {
            "transaction_id": "8e4cb8cf-79da-49ab-aa35-865d1105b45e",
            "status": "success",
            "service_type": service_type,
            "product_type": product_type,
            "network": network,
            "beneficiary": beneficiary,
            "amount": str(amount),
            "vendor_code": vendor_code,
            "vendor_reference": f"{vendor_code}-reference",
            "message": "Transaction success",
        }


def agent_request() -> AgentRequest:
    return AgentRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000001",
        amount=Decimal("5000.00"),
    )


def execute(
    *,
    candidate_vendor: str | None,
) -> tuple[AgentResult, RecordingMCPBusinessTools]:
    client = RecordingMCPBusinessTools()
    planner = FakePlanner(valid_plan(candidate_vendor=candidate_vendor))
    runtime = AgentRuntime(
        TransactionOrchestrator(planner, client)  # type: ignore[arg-type]
    )
    result = asyncio.run(runtime.execute(agent_request()))
    return result, client


def test_planner_candidate_is_propagated_into_agent_result():
    result, _ = execute(candidate_vendor="vendor_a")

    assert isinstance(result, AgentResult)
    assert result.planner_candidate_vendor == "vendor_a"


def test_planner_candidate_is_none_when_planner_proposes_no_candidate():
    result, _ = execute(candidate_vendor=None)

    assert result.planner_candidate_vendor is None


def test_planner_candidate_does_not_override_deterministic_switcher():
    result, client = execute(candidate_vendor="vendor_b")

    assert result.planner_candidate_vendor == "vendor_b"
    assert result.vendor_code == "vendor_a"
    assert client.execution_calls[0]["vendor_code"] == "vendor_a"


def test_unavailable_planner_candidate_still_uses_switcher_choice():
    set_vendor_availability("vendor_a", False)
    try:
        result, client = execute(candidate_vendor="vendor_a")
    finally:
        reset_vendor_availability()

    assert result.planner_candidate_vendor == "vendor_a"
    assert result.vendor_code == "vendor_b"
    assert client.execution_calls[0]["vendor_code"] == "vendor_b"


def test_agent_result_defaults_planner_candidate_to_none() -> None:
    result = AgentResult(
        status="success",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000001",
        amount=Decimal("5000.00"),
        message="Transaction success",
    )

    assert result.planner_candidate_vendor is None


def test_agent_result_preserves_all_existing_fields():
    result, _ = execute(candidate_vendor="vendor_a")

    assert str(result.transaction_id) == "8e4cb8cf-79da-49ab-aa35-865d1105b45e"
    assert result.status == "success"
    assert result.service_type == "airtime"
    assert result.product_type == "airtime"
    assert result.network == "MTN"
    assert result.beneficiary == "08030000001"
    assert result.amount == Decimal("5000.00")
    assert result.vendor_code == "vendor_a"
    assert result.vendor_reference == "vendor_a-reference"
    assert result.action == "allow"
    assert result.reason is None
    assert result.message == "Transaction success"
