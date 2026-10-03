"""Canonical business capability and workflow definitions."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class CapabilityOperation(str, Enum):
    """Business operations a capability may expose through a vendor."""

    AUTHENTICATE = "authenticate"
    VALIDATE_CUSTOMER = "validate_customer"
    EXECUTE_TRANSACTION = "execute_transaction"
    QUERY_TRANSACTION = "query_transaction"


@dataclass(frozen=True)
class WorkflowStep:
    """One ordered operation in a capability workflow."""

    operation: CapabilityOperation
    required: bool = True


@dataclass(frozen=True)
class Capability:
    """A vendor-backed capability identified by canonical business terms."""

    vendor_code: str
    service_type: str
    product_type: str
    network: str | None
    supported_operations: frozenset[CapabilityOperation]
    workflow: tuple[WorkflowStep, ...]
    product_attributes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Ensure the workflow is meaningful and uses supported operations."""
        if not self.workflow:
            raise ValueError("Capability workflow must contain at least one step")

        unsupported_operations = {
            step.operation
            for step in self.workflow
            if step.operation not in self.supported_operations
        }
        if unsupported_operations:
            operations = ", ".join(
                operation.value for operation in sorted(unsupported_operations)
            )
            raise ValueError(f"Workflow contains unsupported operations: {operations}")
