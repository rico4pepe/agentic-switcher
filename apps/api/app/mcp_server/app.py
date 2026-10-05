"""Minimal MCP server boundary."""

from pydantic import BaseModel
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from apps.api.app.database import SessionLocal
from capabilities.domain import Capability
from capabilities.registry import CapabilityRegistry


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
