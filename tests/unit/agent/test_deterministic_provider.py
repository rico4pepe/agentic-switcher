"""Tests for the deterministic development/demo planner provider."""

from decimal import Decimal

import pytest
from pydantic import BaseModel

from agent.deterministic_provider import (
    DeterministicPlannerProvider,
    DeterministicPlannerProviderError,
)
from agent.execution_plan import ExecutionPlan, PlanStep
from agent.llm_provider import LLMProvider
from agent.planner import ExecutionPlanPlanner, PlannerRequest
from capabilities.domain import Capability, CapabilityOperation, WorkflowStep


def airtime_capability(*, vendor_code: str = "vendor_a") -> Capability:
    """Build the canonical MTN airtime capability used by the demo flow."""
    return Capability(
        vendor_code=vendor_code,
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        supported_operations=frozenset(CapabilityOperation),
        workflow=(
            WorkflowStep(CapabilityOperation.AUTHENTICATE, required=True),
            WorkflowStep(CapabilityOperation.VALIDATE_CUSTOMER, required=True),
            WorkflowStep(CapabilityOperation.EXECUTE_TRANSACTION, required=True),
            WorkflowStep(CapabilityOperation.QUERY_TRANSACTION, required=True),
        ),
    )


def planner_request(capabilities: tuple[Capability, ...]) -> PlannerRequest:
    """Build the MTN airtime demo request the orchestrator would supply."""
    return PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=capabilities,
    )


def planner_prompt(*, capabilities: tuple[Capability, ...]) -> str:
    """Build a prompt with the real planner boundary prompt format."""
    return ExecutionPlanPlanner._build_prompt(
        planner_request(capabilities),
        capabilities,
    )


def expected_mtn_airtime_plan() -> ExecutionPlan:
    """The deterministic MTN airtime demo plan the provider should produce."""
    return ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        candidate_vendor="vendor_a",
        steps=(
            PlanStep.VALIDATE_CUSTOMER,
            PlanStep.EXECUTE_TRANSACTION,
        ),
    )


def test_provider_accepts_expected_mtn_airtime_planner_prompt():
    provider = DeterministicPlannerProvider()
    prompt = planner_prompt(capabilities=(airtime_capability(),))

    plan = provider.generate_structured(prompt, ExecutionPlan)

    assert isinstance(plan, ExecutionPlan)
    assert plan == expected_mtn_airtime_plan()


def test_produced_plan_is_structurally_valid():
    provider = DeterministicPlannerProvider()
    prompt = planner_prompt(capabilities=(airtime_capability(),))

    plan = provider.generate_structured(prompt, ExecutionPlan)

    plan.validate_against_capability(airtime_capability())


def test_required_execution_step_is_present():
    provider = DeterministicPlannerProvider()
    prompt = planner_prompt(capabilities=(airtime_capability(),))

    plan = provider.generate_structured(prompt, ExecutionPlan)

    assert PlanStep.VALIDATE_CUSTOMER in plan.steps
    assert PlanStep.EXECUTE_TRANSACTION in plan.steps


def test_proposes_vendor_a_candidate_for_normal_demo_scenario():
    provider = DeterministicPlannerProvider()

    plan = provider.generate_structured(
        planner_prompt(capabilities=(airtime_capability(),)),
        ExecutionPlan,
    )

    assert plan.candidate_vendor == "vendor_a"


def test_candidate_vendor_remains_advisory_when_vendor_a_is_absent():
    provider = DeterministicPlannerProvider()

    plan = provider.generate_structured(
        planner_prompt(capabilities=(airtime_capability(vendor_code="vendor_b"),)),
        ExecutionPlan,
    )

    assert plan.candidate_vendor is None


def test_multiple_vendor_capabilities_still_produce_valid_demo_plan():
    provider = DeterministicPlannerProvider()
    capabilities = (
        airtime_capability(vendor_code="vendor_a"),
        airtime_capability(vendor_code="vendor_b"),
    )

    plan = provider.generate_structured(
        planner_prompt(capabilities=capabilities),
        ExecutionPlan,
    )

    assert plan.candidate_vendor == "vendor_a"
    plan.validate_against_capability(airtime_capability(vendor_code="vendor_a"))
    unselected_plan = plan.model_copy(update={"candidate_vendor": None})
    unselected_plan.validate_against_capability(
        airtime_capability(vendor_code="vendor_b")
    )


def test_output_is_deterministic_and_repeatable():
    provider = DeterministicPlannerProvider()
    prompt = planner_prompt(
        capabilities=(
            airtime_capability(vendor_code="vendor_a"),
            airtime_capability(vendor_code="vendor_b"),
        )
    )

    first = provider.generate_structured(prompt, ExecutionPlan)
    second = provider.generate_structured(prompt, ExecutionPlan)

    assert first == second
    assert first.model_dump() == second.model_dump()


def test_planner_boundary_accepts_deterministic_provider():
    provider = DeterministicPlannerProvider()
    planner = ExecutionPlanPlanner(provider)
    request = planner_request((airtime_capability(),))

    plan = planner.generate(request)

    assert plan == expected_mtn_airtime_plan()


def test_unsupported_output_model_raises_provider_error():
    provider = DeterministicPlannerProvider()

    with pytest.raises(
        DeterministicPlannerProviderError,
        match="only supports ExecutionPlan output",
    ):
        provider.generate_structured("any prompt", BaseModel)


def test_malformed_prompt_raises_provider_error():
    provider = DeterministicPlannerProvider()

    with pytest.raises(DeterministicPlannerProviderError):
        provider.generate_structured("not a planner prompt", ExecutionPlan)


def test_missing_required_planner_steps_raise_provider_error():
    provider = DeterministicPlannerProvider()

    with pytest.raises(
        DeterministicPlannerProviderError,
        match="required planner steps",
    ):
        provider.generate_structured(
            "intent=airtime_purchase\nservice_type=airtime\n"
            "product_type=airtime\nnetwork=MTN\nbeneficiary=08030000000\n"
            "amount=5000\n\nAvailable canonical capabilities:\n",
            ExecutionPlan,
        )


def test_provider_satisfies_llm_provider_contract():
    assert isinstance(DeterministicPlannerProvider(), LLMProvider)