"""Minimal MCP server boundary."""

from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings


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
