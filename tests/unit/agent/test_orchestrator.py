"""Tests for the transaction orchestration boundary."""

import asyncio
from decimal import Decimal
from typing import Mapping
from uuid import UUID

import pytest

from agent.execution_plan import ExecutionPlan, PlanStep
from agent.orchestrator.service import (
    OrchestrationRequest,
    TransactionOrchestrator,
    UnsupportedTransactionCapabilityError,
)
from agent.planner import PlannerRequest
from capabilities.domain import CapabilityOperation
from policy.account_context import AccountContext, AccountType, DemoAccountContextProvider
from policy.engine import PolicyEngine
from switcher.routing import (
    reset_vendor_availability,
    resolve_execution_vendor_code,
    set_vendor_availability,
)


def capability_dto(
    vendor_code: str,
    *,
    include_execute: bool = True,
) -> dict[str, object]:
    operations = [
        "authenticate",
        "validate_customer",
        "query_transaction",
    ]
    workflow = [
        {"operation": "authenticate", "required": True},
        {"operation": "validate_customer", "required": True},
        {"operation": "query_transaction", "required": True},
    ]
    if include_execute:
        operations.append("execute_transaction")
        workflow.insert(
            2,
            {"operation": "execute_transaction", "required": True},
        )
    return {
        "vendor_code": vendor_code,
        "service_type": "airtime",
        "product_type": "airtime",
        "network": "MTN",
        "supported_operations": operations,
        "workflow": workflow,
        "product_attributes": {},
    }


def valid_plan(
    *,
    beneficiary: str = "08030000001",
    amount: Decimal = Decimal("5000.00"),
    candidate_vendor: str | None = None,
    steps: tuple[PlanStep, ...] = (
        PlanStep.VALIDATE_CUSTOMER,
        PlanStep.EXECUTE_TRANSACTION,
    ),
) -> ExecutionPlan:
    return ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary=beneficiary,
        amount=amount,
        candidate_vendor=candidate_vendor,
        steps=steps,
    )


class FakeMCPBusinessTools:
    def __init__(
        self,
        capabilities: list[dict[str, object]] | None = None,
        execution_result: Mapping[str, object] | None = None,
    ) -> None:
        self.capabilities = capabilities or [
            capability_dto("vendor_a"),
            capability_dto("vendor_b"),
        ]
        self.execution_result = execution_result or {
            "status": "success",
            "transaction_id": "transaction-123",
        }
        self.discovery_calls: list[dict[str, object]] = []
        self.execution_calls: list[dict[str, object]] = []

    async def find_transaction_capabilities(
        self,
        *,
        service_type: str,
        product_type: str,
        network: str | None,
    ) -> Mapping[str, object]:
        self.discovery_calls.append(
            {
                "service_type": service_type,
                "product_type": product_type,
                "network": network,
            }
        )
        return {"capabilities": self.capabilities}

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
        return self.execution_result


class FakePlanner:
    def __init__(self, plan: ExecutionPlan) -> None:
        self.plan = plan
        self.requests: list[PlannerRequest] = []

    def generate(self, request: PlannerRequest) -> ExecutionPlan:
        self.requests.append(request)
        return self.plan


def orchestration_request(**overrides: object) -> OrchestrationRequest:
    values: dict[str, object] = {
        "intent": "airtime_purchase",
        "service_type": "airtime",
        "product_type": "airtime",
        "network": "MTN",
        "beneficiary": "08030000001",
        "amount": Decimal("5000.00"),
    }
    values.update(overrides)
    return OrchestrationRequest(**values)


def test_success_discovers_plans_validates_and_executes(monkeypatch: pytest.MonkeyPatch):
    client = FakeMCPBusinessTools()
    planner = FakePlanner(valid_plan())
    expected_key = UUID("00000000-0000-0000-0000-000000000123")
    monkeypatch.setattr("agent.orchestrator.service.uuid4", lambda: expected_key)
    orchestrator = TransactionOrchestrator(
        planner,  # type: ignore[arg-type]
        client,
    )

    result = asyncio.run(orchestrator.execute(orchestration_request()))

    assert result == {
        **client.execution_result,
        "action": "allow",
        "planner_candidate_vendor": None,
    }
    assert client.discovery_calls == [
        {
            "service_type": "airtime",
            "product_type": "airtime",
            "network": "MTN",
        }
    ]
    assert len(planner.requests) == 1
    assert [
        capability.vendor_code for capability in planner.requests[0].capabilities
    ] == ["vendor_a", "vendor_b"]
    assert all(
        CapabilityOperation.EXECUTE_TRANSACTION in capability.supported_operations
        for capability in planner.requests[0].capabilities
    )
    assert client.execution_calls == [
        {
            "service_type": "airtime",
            "product_type": "airtime",
            "network": "MTN",
            "beneficiary": "08030000001",
            "amount": Decimal("5000.00"),
            "vendor_code": "vendor_a",
            "idempotency_key": str(expected_key),
        }
    ]
    assert not hasattr(planner.requests[0], "idempotency_key")


def test_non_vendor_a_executable_capability_is_passed_to_planner_and_mcp():
    client = FakeMCPBusinessTools(capabilities=[capability_dto("vendor_b")])
    planner = FakePlanner(valid_plan(candidate_vendor="vendor_b"))
    orchestrator = TransactionOrchestrator(planner, client)  # type: ignore[arg-type]

    result = asyncio.run(orchestrator.execute(orchestration_request()))

    assert result == {
        **client.execution_result,
        "action": "allow",
        "planner_candidate_vendor": "vendor_b",
    }
    assert [capability.vendor_code for capability in planner.requests[0].capabilities] == [
        "vendor_b"
    ]
    assert len(client.execution_calls) == 1


def test_candidate_vendor_unavailable_falls_through_in_orchestrator():
    client = FakeMCPBusinessTools()
    planner = FakePlanner(valid_plan(candidate_vendor="vendor_a"))
    orchestrator = TransactionOrchestrator(planner, client)  # type: ignore[arg-type]
    set_vendor_availability("vendor_a", False)
    try:
        result = asyncio.run(orchestrator.execute(orchestration_request()))
    finally:
        reset_vendor_availability()

    assert result["status"] == "success"
    assert client.execution_calls[0]["vendor_code"] == "vendor_b"


def test_candidate_vendor_does_not_override_deterministic_priority():
    capabilities = tuple(
        TransactionOrchestrator._capability_from_dto(capability_dto(vendor_code))
        for vendor_code in ("vendor_b", "vendor_a")
    )

    assert resolve_execution_vendor_code(
        valid_plan(candidate_vendor="vendor_b"),
        capabilities,
    ) == "vendor_a"


def test_unavailable_candidate_falls_through_to_eligible_vendor():
    capabilities = tuple(
        TransactionOrchestrator._capability_from_dto(capability_dto(vendor_code))
        for vendor_code in ("vendor_a", "vendor_b")
    )
    set_vendor_availability("vendor_a", False)
    try:
        selected_vendor = resolve_execution_vendor_code(
            valid_plan(candidate_vendor="vendor_a"),
            capabilities,
        )
    finally:
        reset_vendor_availability()

    assert selected_vendor == "vendor_b"


def test_changed_beneficiary_is_rejected_before_execution():
    client = FakeMCPBusinessTools()
    planner = FakePlanner(valid_plan(beneficiary="08039999999"))
    orchestrator = TransactionOrchestrator(planner, client)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="beneficiary"):
        asyncio.run(orchestrator.execute(orchestration_request()))

    assert client.execution_calls == []


def test_changed_amount_is_rejected_before_execution():
    client = FakeMCPBusinessTools()
    planner = FakePlanner(valid_plan(amount=Decimal("7000.00")))
    orchestrator = TransactionOrchestrator(planner, client)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="amount"):
        asyncio.run(orchestrator.execute(orchestration_request()))

    assert client.execution_calls == []


def test_plan_incompatible_with_capability_is_rejected_before_execution():
    client = FakeMCPBusinessTools()
    planner = FakePlanner(
        valid_plan(steps=(PlanStep.EXECUTE_TRANSACTION,))
    )
    orchestrator = TransactionOrchestrator(planner, client)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="incompatible with executable capability"):
        asyncio.run(orchestrator.execute(orchestration_request()))

    assert client.execution_calls == []


def test_model_cannot_select_a_vendor_outside_deterministic_capability_path():
    client = FakeMCPBusinessTools()
    planner = FakePlanner(valid_plan(candidate_vendor="vendor_c"))
    orchestrator = TransactionOrchestrator(planner, client)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="incompatible with executable capability"):
        asyncio.run(orchestrator.execute(orchestration_request()))

    assert client.execution_calls == []
    assert "vendor_code" not in OrchestrationRequest.__annotations__


def test_no_executable_capability_does_not_invoke_planner_or_execution():
    client = FakeMCPBusinessTools(
        capabilities=[
            capability_dto("vendor_a", include_execute=False),
            capability_dto("vendor_b", include_execute=False),
        ]
    )
    planner = FakePlanner(valid_plan())
    orchestrator = TransactionOrchestrator(planner, client)  # type: ignore[arg-type]

    with pytest.raises(UnsupportedTransactionCapabilityError):
        asyncio.run(orchestrator.execute(orchestration_request()))

    assert planner.requests == []
    assert client.execution_calls == []


def test_policy_denial_cannot_be_overridden_by_planner_vendor_choice(
    monkeypatch: pytest.MonkeyPatch,
):
    client = FakeMCPBusinessTools()
    planner = FakePlanner(valid_plan(candidate_vendor="vendor_a"))
    policy_engine = PolicyEngine(
        DemoAccountContextProvider(
            (
                AccountContext(
                    beneficiary="08030000001",
                    account_type=AccountType.PREPAID,
                    balance=Decimal("2000.00"),
                ),
            )
        )
    )
    orchestrator = TransactionOrchestrator(
        planner,  # type: ignore[arg-type]
        client,
        policy_engine=policy_engine,
    )

    def unexpected_vendor_selection(*_args, **_kwargs):
        raise AssertionError("Denied requests must not select a vendor")

    monkeypatch.setattr(
        "agent.orchestrator.service.resolve_execution_vendor_code",
        unexpected_vendor_selection,
    )
    result = asyncio.run(orchestrator.execute(orchestration_request()))

    assert result["action"] == "deny"
    assert result["reason"] == "Insufficient balance"
    assert result["transaction_id"] is None
    assert result["vendor_code"] is None
    assert result["vendor_reference"] is None
    assert client.execution_calls == []


def test_unknown_result_is_returned_without_retry():
    unknown_result = {
        "status": "unknown",
        "transaction_id": "transaction-unknown",
    }
    client = FakeMCPBusinessTools(execution_result=unknown_result)
    orchestrator = TransactionOrchestrator(
        FakePlanner(valid_plan()),  # type: ignore[arg-type]
        client,
    )

    result = asyncio.run(orchestrator.execute(orchestration_request()))

    assert result == {
        **unknown_result,
        "action": "allow",
        "planner_candidate_vendor": None,
    }
    assert len(client.execution_calls) == 1
