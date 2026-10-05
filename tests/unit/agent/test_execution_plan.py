"""Tests for the structured execution plan."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent.execution_plan import ExecutionPlan, PlanStep
from capabilities.domain import Capability, CapabilityOperation, WorkflowStep


def airtime_capability(*, include_optional_query: bool = False) -> Capability:
    workflow = (
        WorkflowStep(CapabilityOperation.AUTHENTICATE, required=True),
        WorkflowStep(CapabilityOperation.VALIDATE_CUSTOMER, required=True),
        WorkflowStep(CapabilityOperation.EXECUTE_TRANSACTION, required=True),
        WorkflowStep(
            CapabilityOperation.QUERY_TRANSACTION,
            required=not include_optional_query,
        ),
    )
    return Capability(
        vendor_code="vendor_a",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        supported_operations=frozenset(CapabilityOperation),
        workflow=workflow,
    )


def test_valid_airtime_execution_plan_is_accepted():
    plan = ExecutionPlan(
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

    assert plan.intent == "airtime_purchase"
    assert plan.service_type == "airtime"
    assert plan.product_type == "airtime"
    assert plan.network == "MTN"
    assert plan.beneficiary == "08030000000"
    assert plan.amount == Decimal("5000")
    assert plan.candidate_vendor == "vendor_a"


def test_candidate_vendor_is_optional():
    plan = ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        steps=(PlanStep.EXECUTE_TRANSACTION,),
    )

    assert plan.candidate_vendor is None


def test_amount_must_be_greater_than_zero():
    with pytest.raises(ValidationError):
        ExecutionPlan(
            intent="airtime_purchase",
            service_type="airtime",
            product_type="airtime",
            network="MTN",
            beneficiary="08030000000",
            amount=Decimal("0"),
            steps=(PlanStep.EXECUTE_TRANSACTION,),
        )


def test_steps_must_use_supported_plan_operations():
    with pytest.raises(ValidationError):
        ExecutionPlan(
            intent="airtime_purchase",
            service_type="airtime",
            product_type="airtime",
            network="MTN",
            beneficiary="08030000000",
            amount=Decimal("5000"),
            steps=("call_vendor_api",),
        )


def test_plan_requires_at_least_one_step():
    with pytest.raises(ValidationError):
        ExecutionPlan(
            intent="airtime_purchase",
            service_type="airtime",
            product_type="airtime",
            network="MTN",
            beneficiary="08030000000",
            amount=Decimal("5000"),
            steps=(),
        )


def test_plan_is_not_a_transaction_result():
    plan = ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        steps=(PlanStep.EXECUTE_TRANSACTION,),
    )

    assert not hasattr(plan, "transaction_id")
    assert not hasattr(plan, "vendor_reference")
    assert not hasattr(plan, "state")


def test_valid_plan_passes_capability_validation():
    plan = ExecutionPlan(
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

    plan.validate_against_capability(airtime_capability())


def test_unsupported_plan_step_fails_capability_validation():
    with pytest.raises(ValidationError):
        ExecutionPlan(
            intent="airtime_purchase",
            service_type="airtime",
            product_type="airtime",
            network="MTN",
            beneficiary="08030000000",
            amount=Decimal("5000"),
            steps=("call_vendor_api",),
        )


def test_empty_steps_fail_capability_validation():
    with pytest.raises(ValidationError):
        ExecutionPlan(
            intent="airtime_purchase",
            service_type="airtime",
            product_type="airtime",
            network="MTN",
            beneficiary="08030000000",
            amount=Decimal("5000"),
            steps=(),
        )


def test_missing_required_planner_visible_step_fails_capability_validation():
    plan = ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        steps=(PlanStep.EXECUTE_TRANSACTION,),
    )

    with pytest.raises(ValueError):
        plan.validate_against_capability(airtime_capability())


def test_optional_workflow_step_can_be_omitted():
    plan = ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        steps=(
            PlanStep.VALIDATE_CUSTOMER,
            PlanStep.EXECUTE_TRANSACTION,
        ),
    )

    plan.validate_against_capability(airtime_capability(include_optional_query=True))


def test_mismatched_service_product_network_fails_capability_validation():
    plan = ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="data",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        steps=(
            PlanStep.VALIDATE_CUSTOMER,
            PlanStep.EXECUTE_TRANSACTION,
        ),
    )

    with pytest.raises(ValueError):
        plan.validate_against_capability(airtime_capability())


def test_invalid_candidate_vendor_fails_capability_validation():
    plan = ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        candidate_vendor="vendor_b",
        steps=(
            PlanStep.VALIDATE_CUSTOMER,
            PlanStep.EXECUTE_TRANSACTION,
        ),
    )

    with pytest.raises(ValueError):
        plan.validate_against_capability(airtime_capability())


def test_matching_candidate_vendor_passes_capability_validation():
    plan = ExecutionPlan(
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

    plan.validate_against_capability(airtime_capability())


def test_authenticate_and_query_transaction_are_not_required_in_planner_plan():
    plan = ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        steps=(
            PlanStep.VALIDATE_CUSTOMER,
            PlanStep.EXECUTE_TRANSACTION,
        ),
    )

    plan.validate_against_capability(airtime_capability())


def test_duplicate_steps_are_rejected():
    plan = ExecutionPlan(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000"),
        steps=(
            PlanStep.VALIDATE_CUSTOMER,
            PlanStep.VALIDATE_CUSTOMER,
        ),
    )

    with pytest.raises(ValueError):
        plan.validate_against_capability(airtime_capability())