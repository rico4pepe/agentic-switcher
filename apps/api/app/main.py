"""FastAPI application entry point for Agentic Switcher."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.app.mcp_server.app import (
    create_mcp_server,
    mcp_asgi_app,
    set_active_mcp_server,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run MCP session infrastructure for the lifetime of the host API."""
    mcp_server, sdk_app = create_mcp_server()
    mcp_asgi_app.set_application(sdk_app)
    set_active_mcp_server(mcp_server)
    try:
        async with mcp_server.session_manager.run():
            yield
    finally:
        set_active_mcp_server(None)
        mcp_asgi_app.set_application(None)


app = FastAPI(
    title="Agentic Switcher",
    description="Agentic transaction orchestration and operations platform",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Return the health status of the API."""
    return {
        "status": "ok",
        "service": "agentic-switcher-api",
    }


app.mount("/mcp", mcp_asgi_app)

# Demo scenario router
from apps.api.app.demo_scenarios import router as demo_router

app.include_router(demo_router)

# Conversation API router
from apps.api.app.chat import router as chat_router

app.include_router(chat_router)
