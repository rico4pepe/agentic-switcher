"""Minimal MCP server boundary."""

import logging
from decimal import Decimal
from uuid import UUID

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from apps.api.app.config import settings
from apps.api.app.database import SessionLocal
from apps.api.app.domain.transaction import Transaction, TransactionState
from capabilities.domain import Capability, CapabilityOperation
from capabilities.registry import CapabilityRegistry
from policy.engine import PolicyAction, PolicyEngine, default_policy_engine
from switcher.routing import get_vendor_availability, resolve_execution_vendor_code
from switcher.transactions.execution_service import TransactionExecutionService
from switcher.transactions.investigator import (
    TransactionInvestigator,
    TransactionStatusOutput,
)
from switcher.transactions.persistence_service import (
    IdempotencyConflictError,
    PersistedTransactionExecutionService,
)
from switcher.vendor_adapter_resolver import (
    UnsupportedVendorError,
    VendorAuthenticationError,
    create_authenticated_adapter,
)
from vendors.vendor_a import VendorAAdapter


logger = logging.getLogger(__name__)


def request_to_plan(request: "ExecuteTransactionRequest") -> object:
    """Create a minimal execution plan for deterministic vendor routing checks."""
    from agent.execution_plan import ExecutionPlan, PlanStep

    return ExecutionPlan(
        intent="execute_transaction",
        service_type=request.service_type,
        product_type=request.product_type,
        network=request.network,
        beneficiary=request.beneficiary,
        amount=request.amount,
        candidate_vendor=None,
        steps=(
            PlanStep.VALIDATE_CUSTOMER,
            PlanStep.EXECUTE_TRANSACTION,
        ),
    )


class CapabilityWorkflowStepOutput(BaseModel):
    """JSON-safe workflow step returned by the capability lookup tool."""

    operation: str
    required: bool


class CapabilityOutput(BaseModel):
    """JSON-safe canonical capability returned by the MCP tool."""

    vendor_code: str
    service_type: str
    product_type: str
    network: str | None
    supported_operations: list[str]
    workflow: list[CapabilityWorkflowStepOutput]
    product_attributes: dict[str, str]


class FindTransactionCapabilitiesOutput(BaseModel):
    """Result envelope for exact capability lookup."""

    capabilities: list[CapabilityOutput]


class ExecuteTransactionRequest(BaseModel):
    """Business-level request accepted by the MCP execution tool."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    service_type: str = Field(min_length=1, max_length=50)
    product_type: str = Field(min_length=1, max_length=50)
    network: str | None = Field(default=None, max_length=50)
    beneficiary: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=255)


class ExecuteTransactionOutput(BaseModel):
    """Business result based on the canonical persisted transaction."""

    transaction_id: UUID | None
    status: str
    service_type: str
    product_type: str
    network: str | None
    beneficiary: str
    amount: Decimal
    vendor_code: str | None = None
    vendor_reference: str | None
    message: str
    action: str
    reason: str | None = None


class GetTransactionStatusRequest(BaseModel):
    """Read-only business request for a persisted transaction status lookup."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    transaction_id: UUID


def _serialize_capability(capability: Capability) -> CapabilityOutput:
    return CapabilityOutput(
        vendor_code=capability.vendor_code,
        service_type=capability.service_type,
        product_type=capability.product_type,
        network=capability.network,
        supported_operations=sorted(
            operation.value for operation in capability.supported_operations
        ),
        workflow=[
            CapabilityWorkflowStepOutput(
                operation=step.operation.value,
                required=step.required,
            )
            for step in capability.workflow
        ],
        product_attributes=dict(capability.product_attributes),
    )


def _execute_transaction(
    request: ExecuteTransactionRequest,
    *,
    policy_engine: PolicyEngine = default_policy_engine,
) -> ExecuteTransactionOutput:
    decision = policy_engine.evaluate(request.beneficiary, request.amount)
    if decision.action == PolicyAction.DENY:
        return ExecuteTransactionOutput(
            transaction_id=None,
            status="denied",
            service_type=request.service_type,
            product_type=request.product_type,
            network=request.network,
            beneficiary=request.beneficiary,
            amount=request.amount,
            vendor_code=None,
            vendor_reference=None,
            message=decision.reason,
            action=decision.action.value,
            reason=decision.reason,
        )

    try:
        with SessionLocal() as session:
            capabilities = CapabilityRegistry(session).find(
                service_type=request.service_type,
                product_type=request.product_type,
                network=request.network,
            )

            executable_capabilities = tuple(
                capability
                for capability in capabilities
                if CapabilityOperation.EXECUTE_TRANSACTION
                in capability.supported_operations
                and get_vendor_availability(capability.vendor_code)
            )
            if not executable_capabilities:
                raise ToolError("Unsupported transaction capability")

            selected_vendor = resolve_execution_vendor_code(
                request_to_plan(request),
                capabilities,
            )

            executable_capability = next(
                (
                    capability
                    for capability in executable_capabilities
                    if capability.vendor_code == selected_vendor
                ),
                None,
            )
            if executable_capability is None:
                raise ToolError("Unsupported transaction capability")

            def create_execution_service() -> TransactionExecutionService:
                adapter = create_authenticated_adapter(
                    executable_capability.vendor_code,
                    settings,
                )
                return TransactionExecutionService(adapter)

            transaction = Transaction(
                product_type=request.product_type,
                network=request.network,
                beneficiary=request.beneficiary,
                amount=request.amount,
                vendor_code=executable_capability.vendor_code,
                idempotency_key=request.idempotency_key,
            )
            canonical = PersistedTransactionExecutionService(
                session,
                create_execution_service,
            ).execute(transaction)
    except ToolError:
        raise
    except IdempotencyConflictError as error:
        raise ToolError(str(error)) from error
    except VendorAuthenticationError as error:
        raise ToolError("Vendor adapter authentication failed") from error
    except UnsupportedVendorError as error:
        logger.exception("MCP vendor resolution failed")
        raise ToolError("Transaction execution is unavailable") from error
    except Exception as error:
        logger.exception("MCP transaction execution failed")
        raise ToolError("Transaction execution could not be completed") from error

    state = canonical.state
    if state == TransactionState.SUCCESS:
        message = "Transaction completed successfully"
    elif state == TransactionState.FAILED:
        message = canonical.error_message or "Transaction failed"
    elif state == TransactionState.UNKNOWN:
        message = canonical.error_message or "Transaction outcome is unknown"
    else:
        message = canonical.error_message or f"Transaction status: {state.value}"

    return ExecuteTransactionOutput(
        transaction_id=canonical.id,
        status=state.value,
        service_type=request.service_type,
        product_type=canonical.product_type,
        network=canonical.network,
        beneficiary=canonical.beneficiary or "",
        amount=canonical.amount,
        vendor_code=canonical.vendor_code,
        vendor_reference=canonical.vendor_reference,
        message=message,
        action=PolicyAction.ALLOW.value,
    )


def _get_transaction_status(
    request: GetTransactionStatusRequest,
) -> TransactionStatusOutput:
    try:
        with SessionLocal() as session:
            transaction = session.get(Transaction, request.transaction_id)
            if transaction is None:
                raise ToolError(f"Transaction {request.transaction_id} does not exist")
            if transaction.state not in {
                TransactionState.UNKNOWN,
                TransactionState.SUBMITTING,
                TransactionState.SUBMITTED,
                TransactionState.INVESTIGATING,
                TransactionState.STATUS_RESOLVED,
            }:
                raise ToolError("Transaction is not eligible for status investigation")

            def create_execution_service() -> TransactionExecutionService:
                vendor_code = transaction.vendor_code or VendorAAdapter.VENDOR_CODE
                adapter = create_authenticated_adapter(vendor_code, settings)
                return TransactionExecutionService(adapter)

            canonical = TransactionInvestigator(
                session,
                create_execution_service,
            ).investigate(request.transaction_id)
    except ToolError:
        raise
    except VendorAuthenticationError as error:
        raise ToolError("Vendor adapter authentication failed") from error
    except UnsupportedVendorError as error:
        logger.exception("MCP vendor resolution failed")
        raise ToolError("Transaction status is unavailable") from error
    except LookupError as error:
        raise ToolError(str(error)) from error
    except ValueError as error:
        raise ToolError(str(error)) from error
    except Exception as error:
        logger.exception("MCP transaction status lookup failed")
        raise ToolError("Transaction status could not be determined") from error

    return TransactionStatusOutput(
        transaction_id=canonical.id,
        status=canonical.state.value,
        vendor_reference=canonical.vendor_reference,
        raw_vendor_response=canonical.raw_vendor_response,
        error_message=canonical.error_message,
    )


class MCPASGIDispatcher:
    """Keep a stable mount while recreating the SDK app for each host lifespan."""

    def __init__(self) -> None:
        self._application: ASGIApp | None = None

    def set_application(self, application: ASGIApp | None) -> None:
        self._application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._application is None:
            raise RuntimeError("MCP application is not active")
        await self._application(scope, receive, send)


def create_mcp_server(
    policy_engine: PolicyEngine = default_policy_engine,
) -> tuple[MCPServer, ASGIApp]:
    """Create an MCP server and its Streamable HTTP ASGI application."""
    server = MCPServer(name="Agentic Switcher")

    @server.tool()
    def find_transaction_capabilities(
        service_type: str,
        product_type: str,
        network: str | None,
    ) -> FindTransactionCapabilitiesOutput:
        """Find all canonical capabilities matching exact transaction terms."""
        with SessionLocal() as session:
            matches = CapabilityRegistry(session).find(
                service_type=service_type,
                product_type=product_type,
                network=network,
            )
            serialized = FindTransactionCapabilitiesOutput(
                capabilities=[
                    _serialize_capability(capability) for capability in matches
                ]
            ).model_dump(mode="json")

        return FindTransactionCapabilitiesOutput.model_validate(serialized)

    @server.tool()
    def execute_transaction(
        service_type: str = Field(min_length=1, max_length=50),
        product_type: str = Field(min_length=1, max_length=50),
        network: str | None = Field(default=None, max_length=50),
        beneficiary: str = Field(min_length=1, max_length=100),
        amount: Decimal = Field(gt=0),
        idempotency_key: str = Field(min_length=1, max_length=255),
    ) -> ExecuteTransactionOutput:
        """Execute a transaction through the deterministic persisted business flow."""
        request = ExecuteTransactionRequest(
            service_type=service_type,
            product_type=product_type,
            network=network,
            beneficiary=beneficiary,
            amount=amount,
            idempotency_key=idempotency_key,
        )
        return _execute_transaction(request, policy_engine=policy_engine)

    tool = server._tool_manager.get_tool("execute_transaction")
    if tool is not None:
        properties = dict(tool.parameters.get("properties", {}))
        properties.pop("vendor_code", None)
        required = [
            name for name in tool.parameters.get("required", []) if name != "vendor_code"
        ]
        tool.parameters = {
            **tool.parameters,
            "properties": properties,
            "required": required,
        }

    @server.tool()
    def get_transaction_status(
        transaction_id: UUID,
    ) -> TransactionStatusOutput:
        """Read-only status lookup for a persisted transaction."""
        return _get_transaction_status(
            GetTransactionStatusRequest(transaction_id=transaction_id)
        )

    application = server.streamable_http_app(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            allowed_hosts=[
                "localhost",
                "localhost:*",
                "127.0.0.1",
                "127.0.0.1:*",
            ]
        ),
    )
    return server, application


mcp_asgi_app = MCPASGIDispatcher()

_active_mcp_server: MCPServer | None = None


def set_active_mcp_server(server: MCPServer | None) -> None:
    """Record the MCP server whose business tools the host app exposes."""
    global _active_mcp_server
    _active_mcp_server = server


def get_active_mcp_server() -> MCPServer:
    """Return the active MCP server or fail clearly if the app is not started."""
    if _active_mcp_server is None:
        raise RuntimeError("MCP server is not active")
    return _active_mcp_server
