"""Structured execution plan proposed by the agent."""

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

from capabilities.domain import Capability, CapabilityOperation, WorkflowStep


class PlanStep(str, Enum):
    """Business operations the agent may propose in an execution plan."""

    VALIDATE_CUSTOMER = "validate_customer"
    EXECUTE_TRANSACTION = "execute_transaction"
    QUERY_TRANSACTION = "query_transaction"


def _planner_visible_capability_steps(capability: Capability) -> tuple[WorkflowStep, ...]:
    """Return capability workflow steps that matter to planner-visible business validation."""
    return tuple(
        step
        for step in capability.workflow
        if step.operation not in {
            CapabilityOperation.AUTHENTICATE,
            CapabilityOperation.QUERY_TRANSACTION,
        }
    )


class ExecutionPlan(BaseModel):
    """Structured proposal produced by the agent before deterministic validation."""

    intent: str = Field(min_length=1)
    service_type: str = Field(min_length=1)
    product_type: str = Field(min_length=1)
    network: str | None = None
    beneficiary: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    candidate_vendor: str | None = None
    steps: tuple[PlanStep, ...] = Field(min_length=1)

    def validate_against_capability(self, capability: Capability) -> None:
        """Validate this planning proposal against a canonical capability."""
        if self.service_type != capability.service_type:
            raise ValueError(
                "Plan service_type does not match capability service_type"
            )
        if self.product_type != capability.product_type:
            raise ValueError(
                "Plan product_type does not match capability product_type"
            )
        if self.network != capability.network:
            raise ValueError(
                "Plan network does not match capability network"
            )

        if (
            self.candidate_vendor is not None
            and self.candidate_vendor != capability.vendor_code
        ):
            raise ValueError(
                "Plan candidate_vendor does not match the canonical capability vendor"
            )

        plan_steps = tuple(self.steps)
        if len(set(plan_steps)) != len(plan_steps):
            raise ValueError("Plan contains duplicate steps")

        supported_operations = capability.supported_operations
        plan_operations = {CapabilityOperation(step.value) for step in plan_steps}
        unsupported = plan_operations - supported_operations
        if unsupported:
            operations = ", ".join(sorted(operation.value for operation in unsupported))
            raise ValueError(
                f"Plan contains unsupported capability operations: {operations}"
            )

        required_steps = {
            step.operation
            for step in _planner_visible_capability_steps(capability)
            if step.required
        }
        missing_required = required_steps - plan_operations
        if missing_required:
            operations = ", ".join(sorted(operation.value for operation in missing_required))
            raise ValueError(
                f"Plan is missing required planner-visible capability steps: {operations}"
            )


def validate_execution_plan_against_capability(
    plan: ExecutionPlan,
    capability: Capability,
) -> None:
    """Deterministic check that a planner proposal matches a canonical capability."""
    plan.validate_against_capability(capability)