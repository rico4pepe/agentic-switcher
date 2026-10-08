"""Run structured agent requests through the transaction orchestrator."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.orchestrator.service import (
    OrchestrationRequest,
    TransactionOrchestrator,
)


AgentTransactionStatus = Literal[
    "created",
    "validating",
    "validated",
    "submitting",
    "submitted",
    "success",
    "failed",
    "unknown",
    "investigating",
    "status_resolved",
    "denied",
]


class AgentRequest(BaseModel):
    """Structured business request accepted by the agent runtime."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: str = Field(min_length=1)
    service_type: str = Field(min_length=1, max_length=50)
    product_type: str = Field(min_length=1, max_length=50)
    network: str | None = Field(default=None, max_length=50)
    beneficiary: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0)


class AgentResult(BaseModel):
    """Validated agent-facing view of the authoritative transaction result."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: UUID | None = None
    status: AgentTransactionStatus
    service_type: str
    product_type: str
    network: str | None
    beneficiary: str
    amount: Decimal
    vendor_code: str | None = None
    vendor_reference: str | None = None
    action: Literal["allow", "deny"] | None = None
    reason: str | None = None
    message: str
    planner_candidate_vendor: str | None = None


class InvalidAgentResultError(RuntimeError):
    """Raised when the orchestrator returns a malformed transaction result."""


class AgentRuntime:
    """Validate structured requests and delegate all work to the orchestrator."""

    def __init__(self, orchestrator: TransactionOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def execute(self, request: AgentRequest) -> AgentResult:
        orchestration_request = OrchestrationRequest(
            intent=request.intent,
            service_type=request.service_type,
            product_type=request.product_type,
            network=request.network,
            beneficiary=request.beneficiary,
            amount=request.amount,
        )
        result = await self._orchestrator.execute(orchestration_request)
        try:
            return AgentResult.model_validate(result)
        except ValidationError as error:
            raise InvalidAgentResultError(
                "Transaction orchestrator returned an invalid agent result"
            ) from error