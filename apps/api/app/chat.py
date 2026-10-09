"""Conversation API boundary for natural-language transaction requests.

This module is a thin HTTP boundary. It converts a browser-supplied natural
language message into an :class:`AgentRequest` via the existing
``RequestUnderstanding`` parser, executes it through the existing
``AgentRuntime``/``TransactionOrchestrator`` MCP business-tool path, and
returns the authoritative :class:`AgentResult` plus its deterministic
explanation.

The browser can only send a message. It cannot choose vendors, supply
idempotency keys, control balances, call raw vendor/MCP APIs, or fabricate
outcomes. Demo scenario state is read by the existing runtime, never set here,
so ``/api/chat`` and ``/api/demo`` stay independent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException
from mcp.client import ClientSession
from mcp.client._memory import InMemoryTransport
from pydantic import BaseModel, ConfigDict, Field

from agent.deterministic_provider import DeterministicPlannerProvider
from agent.explainer import TransactionExplainer
from agent.orchestrator.service import (
    MCPBusinessToolError,
    MCPBusinessTools,
    MCPClientBusinessTools,
    TransactionOrchestrator,
    UnsupportedTransactionCapabilityError,
)
from agent.planner import ExecutionPlanPlanner
from agent.request_understanding import RequestUnderstanding, UnsupportedRequestError
from agent.runtime.service import AgentResult, AgentRuntime, InvalidAgentResultError
from apps.api.app.mcp_server.app import get_active_mcp_server


router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    """The only input a browser may supply: a natural-language message."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=1000)


class ChatResponse(AgentResult):
    """Authoritative agent result plus its deterministic explanation."""

    explanation: str


@asynccontextmanager
async def _open_business_tools() -> AsyncIterator[MCPBusinessTools]:
    """Open an in-process MCP session against the host application's server."""
    server = get_active_mcp_server()
    async with InMemoryTransport(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield MCPClientBusinessTools(session)


async def execute_chat(message: str) -> ChatResponse:
    """Parse a message, execute it through the existing runtime, and explain it."""
    request = RequestUnderstanding().parse(message)

    async with _open_business_tools() as business_tools:
        runtime = AgentRuntime(
            TransactionOrchestrator(
                ExecutionPlanPlanner(DeterministicPlannerProvider()),
                business_tools,
            )
        )
        result = await runtime.execute(request)

    return ChatResponse(
        **result.model_dump(),
        explanation=TransactionExplainer().explain(result),
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle one natural-language transaction request."""
    try:
        return await execute_chat(request.message)
    except UnsupportedRequestError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except UnsupportedTransactionCapabilityError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (InvalidAgentResultError, MCPBusinessToolError) as error:
        raise HTTPException(
            status_code=502,
            detail="Transaction execution could not be completed",
        ) from error
