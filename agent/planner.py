"""Minimal planner boundary for producing an ExecutionPlan from business input."""

from decimal import Decimal
from typing import Sequence

from pydantic import BaseModel, Field

from agent.execution_plan import ExecutionPlan
from agent.llm_provider import LLMProvider
from capabilities.domain import Capability, CapabilityOperation


class PlannerRequest(BaseModel):
    """Business request and canonical capability context for planner input."""

    intent: str = Field(min_length=1)
    service_type: str = Field(min_length=1)
    product_type: str = Field(min_length=1)
    network: str | None = None
    beneficiary: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    capabilities: tuple[Capability, ...] = ()


class ExecutionPlanPlanner:
    """Smallest application-level planner boundary using the LLMProvider contract."""

    def __init__(self, llm_provider: LLMProvider) -> None:
        self._llm_provider = llm_provider

    def generate(self, request: PlannerRequest) -> ExecutionPlan:
        """Ask the provider for a plan and validate it against the supplied canonical capabilities."""
        capabilities = tuple(request.capabilities)
        if not capabilities:
            raise ValueError("No canonical capabilities available for planner input")

        plan = self._llm_provider.generate_structured(
            self._build_prompt(request, capabilities),
            ExecutionPlan,
        )

        self._validate_plan_against_capabilities(plan, capabilities)
        return plan

    @staticmethod
    def _validate_plan_against_capabilities(
        plan: ExecutionPlan,
        capabilities: Sequence[Capability],
    ) -> None:
        """Reject plans that are incompatible with every supplied canonical capability."""
        if plan.candidate_vendor is not None:
            for capability in capabilities:
                if capability.vendor_code == plan.candidate_vendor:
                    plan.validate_against_capability(capability)
                    return
            raise ValueError(
                "Plan candidate_vendor does not match any supplied canonical capability"
            )

        for capability in capabilities:
            try:
                plan.validate_against_capability(capability)
            except ValueError:
                continue
            return

        raise ValueError(
            "Plan is not compatible with any supplied canonical capability"
        )

    @staticmethod
    def _planner_required_steps(capability: Capability) -> tuple[str, ...]:
        """Return planner-visible required workflow steps for capability context."""
        required_steps = []
        for step in capability.workflow:
            if step.required and step.operation not in {
                CapabilityOperation.AUTHENTICATE,
                CapabilityOperation.QUERY_TRANSACTION,
            }:
                required_steps.append(step.operation.value)
        return tuple(required_steps)

    @staticmethod
    def _build_prompt(
        request: PlannerRequest,
        capabilities: Sequence[Capability],
    ) -> str:
        """Construct the minimal prompt for a planner-visible business execution plan."""
        capabilities_summary = "\n".join(
            (
                "- "
                f"vendor={capability.vendor_code}, "
                f"service={capability.service_type}, "
                f"product={capability.product_type}, "
                f"network={capability.network}, "
                "required_planner_steps="
                f"{list(ExecutionPlanPlanner._planner_required_steps(capability))}, "
                f"supported={sorted(operation.value for operation in capability.supported_operations)}"
            )
            for capability in capabilities
        )
        return (
            "Produce a transaction execution plan for the business request below. "
            "Use only planner-visible business operations. Do not include adapter "
            "lifecycle operations. The required planner-visible workflow steps are "
            "provided for each canonical capability. Return exactly one "
            "ExecutionPlan.\n\n"
            f"intent={request.intent}\n"
            f"service_type={request.service_type}\n"
            f"product_type={request.product_type}\n"
            f"network={request.network}\n"
            f"beneficiary={request.beneficiary}\n"
            f"amount={request.amount}\n\n"
            "Available canonical capabilities:\n"
            f"{capabilities_summary}"
        )


def generate_execution_plan(
    request: PlannerRequest,
    llm_provider: LLMProvider,
) -> ExecutionPlan:
    """Helper for creating a plan from the minimal planner boundary."""
    return ExecutionPlanPlanner(llm_provider).generate(request)
