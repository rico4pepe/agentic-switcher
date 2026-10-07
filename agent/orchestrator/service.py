"""Orchestrate planner proposals through the existing MCP business tools."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from mcp.client import ClientSession
from pydantic import BaseModel, ConfigDict, Field

from agent.execution_plan import (
    ExecutionPlan,
    PlanStep,
    validate_execution_plan_against_capability,
)
from agent.planner import ExecutionPlanPlanner, PlannerRequest
from capabilities.domain import Capability, CapabilityOperation, WorkflowStep
from switcher.routing import resolve_execution_vendor_code


class OrchestrationRequest(BaseModel):
    """Structured business input owned by the orchestrator."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: str = Field(min_length=1)
    service_type: str = Field(min_length=1, max_length=50)
    product_type: str = Field(min_length=1, max_length=50)
    network: str | None = Field(default=None, max_length=50)
    beneficiary: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0)


class MCPBusinessTools(Protocol):
    """The two business-level MCP tools required for transaction execution."""

    async def find_transaction_capabilities(
        self,
        *,
        service_type: str,
        product_type: str,
        network: str | None,
    ) -> Mapping[str, object]: ...

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
    ) -> Mapping[str, object]: ...


class MCPBusinessToolError(RuntimeError):
    """Raised when an MCP business tool does not return structured content."""


class UnsupportedTransactionCapabilityError(ValueError):
    """Raised when discovery returns no executable capability for this slice."""


class MCPClientBusinessTools:
    """Call only the existing transaction capability and execution MCP tools."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def find_transaction_capabilities(
        self,
        *,
        service_type: str,
        product_type: str,
        network: str | None,
    ) -> Mapping[str, object]:
        result = await self._session.call_tool(
            "find_transaction_capabilities",
            {
                "service_type": service_type,
                "product_type": product_type,
                "network": network,
            },
        )
        return self._structured_content(result, "find_transaction_capabilities")

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
        payload = {
            "service_type": service_type,
            "product_type": product_type,
            "network": network,
            "beneficiary": beneficiary,
            "amount": str(amount),
            "idempotency_key": idempotency_key,
        }
        if vendor_code:
            payload["vendor_code"] = vendor_code
        result = await self._session.call_tool(
            "execute_transaction",
            payload,
        )
        return self._structured_content(result, "execute_transaction")

    @staticmethod
    def _structured_content(
        result: object,
        tool_name: str,
    ) -> Mapping[str, object]:
        if getattr(result, "is_error", False):
            raise MCPBusinessToolError(f"MCP tool {tool_name} returned an error")
        content = getattr(result, "structured_content", None)
        if not isinstance(content, Mapping):
            raise MCPBusinessToolError(
                f"MCP tool {tool_name} returned no structured content"
            )
        return content


class TransactionOrchestrator:
    """Bind a planner proposal to user input, then execute through MCP."""

    def __init__(
        self,
        planner: ExecutionPlanPlanner,
        mcp_tools: MCPBusinessTools,
    ) -> None:
        self._planner = planner
        self._mcp_tools = mcp_tools

    async def execute(
        self,
        request: OrchestrationRequest,
    ) -> Mapping[str, object]:
        capability_result = await self._mcp_tools.find_transaction_capabilities(
            service_type=request.service_type,
            product_type=request.product_type,
            network=request.network,
        )
        capabilities = self._capabilities_from_result(capability_result)
        executable_capabilities = tuple(
            capability
            for capability in capabilities
            if CapabilityOperation.EXECUTE_TRANSACTION
            in capability.supported_operations
        )
        if not executable_capabilities:
            raise UnsupportedTransactionCapabilityError(
                "No executable transaction capability is available"
            )

        planner_request = PlannerRequest(
            intent=request.intent,
            service_type=request.service_type,
            product_type=request.product_type,
            network=request.network,
            beneficiary=request.beneficiary,
            amount=request.amount,
            capabilities=executable_capabilities,
        )
        plan = self._planner.generate(planner_request)
        self._validate_request_binding(plan, request)

        self._validate_plan_capability(
            plan,
            executable_capabilities,
        )
        if PlanStep.EXECUTE_TRANSACTION not in plan.steps:
            raise ValueError("Execution plan does not include execute_transaction")

        vendor_code = self._resolve_execution_vendor_code(plan, executable_capabilities)
        return await self._mcp_tools.execute_transaction(
            service_type=request.service_type,
            product_type=request.product_type,
            network=request.network,
            beneficiary=request.beneficiary,
            amount=request.amount,
            vendor_code=vendor_code,
            idempotency_key=str(uuid4()),
        )

    @staticmethod
    def _capabilities_from_result(
        result: Mapping[str, object],
    ) -> tuple[Capability, ...]:
        capability_data = result.get("capabilities")
        if not isinstance(capability_data, Sequence) or isinstance(
            capability_data,
            str | bytes,
        ):
            raise MCPBusinessToolError(
                "find_transaction_capabilities returned an invalid capability list"
            )
        return tuple(
            TransactionOrchestrator._capability_from_dto(item)
            for item in capability_data
        )

    @staticmethod
    def _capability_from_dto(data: object) -> Capability:
        if not isinstance(data, Mapping):
            raise MCPBusinessToolError("MCP capability result is not an object")

        supported_data = data.get("supported_operations")
        workflow_data = data.get("workflow")
        attributes_data = data.get("product_attributes", {})
        if not isinstance(supported_data, Sequence) or isinstance(
            supported_data,
            str | bytes,
        ):
            raise MCPBusinessToolError("MCP capability has invalid supported operations")
        if not isinstance(workflow_data, Sequence) or isinstance(
            workflow_data,
            str | bytes,
        ):
            raise MCPBusinessToolError("MCP capability has an invalid workflow")
        if not isinstance(attributes_data, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in attributes_data.items()
        ):
            raise MCPBusinessToolError("MCP capability has invalid product attributes")

        network = data.get("network")
        if network is not None and not isinstance(network, str):
            raise MCPBusinessToolError("MCP capability has an invalid network")

        return Capability(
            vendor_code=TransactionOrchestrator._required_string(data, "vendor_code"),
            service_type=TransactionOrchestrator._required_string(data, "service_type"),
            product_type=TransactionOrchestrator._required_string(data, "product_type"),
            network=network,
            supported_operations=frozenset(
                CapabilityOperation(operation)
                for operation in supported_data
                if isinstance(operation, str)
            ),
            workflow=tuple(
                TransactionOrchestrator._workflow_step(step)
                for step in workflow_data
            ),
            product_attributes=dict(attributes_data),
        )

    @staticmethod
    def _required_string(data: Mapping[str, object], field_name: str) -> str:
        value = data.get(field_name)
        if not isinstance(value, str):
            raise MCPBusinessToolError(f"MCP capability has invalid {field_name}")
        return value

    @staticmethod
    def _workflow_step(data: object) -> WorkflowStep:
        if not isinstance(data, Mapping):
            raise MCPBusinessToolError("MCP capability has an invalid workflow step")
        operation = data.get("operation")
        required = data.get("required")
        if not isinstance(operation, str) or not isinstance(required, bool):
            raise MCPBusinessToolError("MCP capability has an invalid workflow step")
        return WorkflowStep(CapabilityOperation(operation), required=required)

    @staticmethod
    def _validate_request_binding(
        plan: ExecutionPlan,
        request: OrchestrationRequest,
    ) -> None:
        bound_fields = (
            "service_type",
            "product_type",
            "network",
            "beneficiary",
            "amount",
        )
        changed_fields = [
            field_name
            for field_name in bound_fields
            if getattr(plan, field_name) != getattr(request, field_name)
        ]
        if changed_fields:
            raise ValueError(
                "Execution plan changed structured request fields: "
                + ", ".join(changed_fields)
            )

    @staticmethod
    def _validate_plan_capability(
        plan: ExecutionPlan,
        capabilities: tuple[Capability, ...],
    ) -> None:
        for capability in capabilities:
            try:
                validate_execution_plan_against_capability(plan, capability)
            except ValueError:
                continue
            return
        raise ValueError("Execution plan is incompatible with executable capability")

    @staticmethod
    def _resolve_execution_vendor_code(
        plan: ExecutionPlan,
        capabilities: tuple[Capability, ...],
    ) -> str:
        return resolve_execution_vendor_code(plan, capabilities)


def _safe_validate_plan_against_capability(
    plan: ExecutionPlan,
    capability: Capability,
) -> bool:
    try:
        validate_execution_plan_against_capability(plan, capability)
    except ValueError:
        return False
    return True