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
from switcher.transactions.execution_service import TransactionExecutionService
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

    transaction_id: UUID
    status: str
    service_type: str
    product_type: str
    network: str | None
    beneficiary: str
    amount: Decimal
    vendor_reference: str | None
    message: str


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


def _execute_transaction(request: ExecuteTransactionRequest) -> ExecuteTransactionOutput:
    try:
        with SessionLocal() as session:
            capabilities = CapabilityRegistry(session).find(
                service_type=request.service_type,
                product_type=request.product_type,
                network=request.network,
            )
            executable_capability = next(
                (
                    capability
                    for capability in capabilities
                    if capability.vendor_code == VendorAAdapter.VENDOR_CODE
                    and CapabilityOperation.EXECUTE_TRANSACTION
                    in capability.supported_operations
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
        vendor_reference=canonical.vendor_reference,
        message=message,
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


def create_mcp_server() -> tuple[MCPServer, ASGIApp]:
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
        return _execute_transaction(request)

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
