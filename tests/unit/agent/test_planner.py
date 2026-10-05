"""Tests for the minimal planner boundary and fake provider."""

from decimal import Decimal

import pytest

from agent.execution_plan import ExecutionPlan, PlanStep
from agent.llm_provider import LLMProvider
from agent.planner import ExecutionPlanPlanner, PlannerRequest
from capabilities.domain import Capability, CapabilityOperation, WorkflowStep


class FakeLLMProvider:
    """Deterministic test fake for the LLMProvider contract."""

    def __init__(self, plan: ExecutionPlan | None = None) -> None:
        self.plan = plan
        self.calls: list[tuple[str, type[ExecutionPlan]]] = []

    def generate_structured(
        self,
        prompt: str,
        output_model: type[ExecutionPlan],
    ) -> ExecutionPlan:
        self.calls.append((prompt, output_model))
        if self.plan is None:
            raise AssertionError("Fake provider should be configured with a plan")
        return self.plan


def airtime_capability(*, vendor_code: str = "vendor_a") -> Capability:
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


def valid_plan(*, candidate_vendor: str | None = None) -> ExecutionPlan:
    return ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        candidate_vendor=candidate_vendor,
        steps=(
            PlanStep.VALIDATE_CUSTOMER,
            PlanStep.EXECUTE_TRANSACTION,
        ),
    )


def test_one_capability_without_candidate_vendor_validates():
    provider = FakeLLMProvider(valid_plan())
    planner = ExecutionPlanPlanner(provider)

    request = PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=(airtime_capability(),),
    )

    result = planner.generate(request)

    assert result == valid_plan()


def test_candidate_vendor_matching_capability_validates():
    provider = FakeLLMProvider(valid_plan(candidate_vendor="vendor_a"))
    planner = ExecutionPlanPlanner(provider)

    request = PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=(airtime_capability(),),
    )

    result = planner.generate(request)

    assert result == valid_plan(candidate_vendor="vendor_a")


def test_multiple_compatible_capabilities_without_candidate_vendor_validates_without_selecting_vendor():
    provider = FakeLLMProvider(valid_plan())
    planner = ExecutionPlanPlanner(provider)

    request = PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=(
            airtime_capability(vendor_code="vendor_a"),
            airtime_capability(vendor_code="vendor_b"),
        ),
    )

    result = planner.generate(request)

    assert result == valid_plan()


def test_no_supplied_capability_is_compatible_rejected():
    provider = FakeLLMProvider(
        ExecutionPlan(
            intent="airtime_purchase",
            service_type="airtime",
            product_type="airtime",
            network="MTN",
            beneficiary="08030000000",
            amount=Decimal("5000"),
            steps=(PlanStep.EXECUTE_TRANSACTION,),
        )
    )
    planner = ExecutionPlanPlanner(provider)

    request = PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=(airtime_capability(vendor_code="vendor_a"),),
    )

    with pytest.raises(ValueError, match="not compatible with any supplied canonical capability"):
        planner.generate(request)


def test_candidate_vendor_not_available_rejected():
    provider = FakeLLMProvider(valid_plan(candidate_vendor="vendor_missing"))
    planner = ExecutionPlanPlanner(provider)

    request = PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=(airtime_capability(vendor_code="vendor_a"),),
    )

    with pytest.raises(ValueError, match="candidate_vendor does not match any supplied canonical capability"):
        planner.generate(request)


def test_prompt_includes_planner_visible_required_workflow_steps():
    provider = FakeLLMProvider(valid_plan())
    planner = ExecutionPlanPlanner(provider)

    request = PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=(airtime_capability(),),
    )

    planner.generate(request)

    prompt = provider.calls[0][0]
    assert "required_planner_steps" in prompt
    assert "validate_customer" in prompt
    assert "execute_transaction" in prompt


def test_prompt_does_not_require_authenticate_or_query_transaction():
    provider = FakeLLMProvider(valid_plan())
    planner = ExecutionPlanPlanner(provider)

    request = PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=(airtime_capability(),),
    )

    planner.generate(request)

    prompt = provider.calls[0][0]
    required_section = prompt.split("required_planner_steps=")[1].split(", supported=")[0]
    assert "authenticate" not in required_section.lower()
    assert "query_transaction" not in required_section.lower()
    assert "validate_customer" in required_section.lower()
    assert "execute_transaction" in required_section.lower()


def test_valid_business_request_plus_matching_capability_produces_valid_plan():
    plan = valid_plan(candidate_vendor="vendor_a")
    provider = FakeLLMProvider(plan)
    planner = ExecutionPlanPlanner(provider)

    request = PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=(airtime_capability(),),
    )

    result = planner.generate(request)

    assert result == plan
    assert provider.calls


def test_planner_output_is_validated_against_capability():
    plan = ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        steps=(PlanStep.EXECUTE_TRANSACTION,),
    )
    provider = FakeLLMProvider(plan)
    planner = ExecutionPlanPlanner(provider)

    request = PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=(airtime_capability(),),
    )

    with pytest.raises(ValueError):
        planner.generate(request)


def test_zero_capabilities_prevents_planner_invocation():
    provider = FakeLLMProvider()
    planner = ExecutionPlanPlanner(provider)

    request = PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=(),
    )

    with pytest.raises(ValueError, match="No canonical capabilities available"):
        planner.generate(request)

    assert provider.calls == []


def test_candidate_vendor_is_optional():
    provider = FakeLLMProvider(valid_plan())
    planner = ExecutionPlanPlanner(provider)

    request = PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=(airtime_capability(),),
    )

    result = planner.generate(request)

    assert result == valid_plan()


def test_fake_provider_satisfies_llm_provider_contract():
    provider = FakeLLMProvider(
        ExecutionPlan(
            intent="airtime_purchase",
            service_type="airtime",
            product_type="airtime",
            network="MTN",
            beneficiary="08030000000",
            amount=Decimal("5000"),
            steps=(PlanStep.EXECUTE_TRANSACTION,),
        )
    )

    assert hasattr(FakeLLMProvider, "generate_structured")
    assert isinstance(provider, LLMProvider)


def test_planner_does_not_perform_capability_lookup_itself():
    provider = FakeLLMProvider(valid_plan())
    planner = ExecutionPlanPlanner(provider)

    request = PlannerRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        capabilities=(airtime_capability(),),
    )

    planner.generate(request)

    assert len(provider.calls) == 1


def test_no_aws_bedrock_dependency_is_required():
    assert "boto3" not in globals()
