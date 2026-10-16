"""Chat API boundary for natural-language transaction requests.

This module is a thin HTTP boundary. In the default ``mode="execute"`` it
converts a browser-supplied natural language message into an
:class:`AgentRequest` via the existing ``RequestUnderstanding`` parser, executes
it through the existing ``AgentRuntime``/``TransactionOrchestrator`` MCP
business-tool path, and returns the authoritative :class:`AgentResult` plus its
deterministic explanation. Legacy clients keep that exact response shape.

In ``mode="conversation"`` the same ``execute_chat`` pipeline is reused as the
single execution path, but a bounded in-memory state machine collects missing
airtime fields, asks for explicit confirmation, and only then executes once.

The browser can only send a message (and choose a mode). It cannot choose
vendors, supply idempotency keys, control balances, call raw vendor/MCP APIs, or
fabricate outcomes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException
from mcp.client import ClientSession
from mcp.client._memory import InMemoryTransport

from agent.deterministic_provider import DeterministicPlannerProvider
from agent.explainer import TransactionExplainer
from agent.orchestrator.mcp_events import MCPCallRecorder, attach_events
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
from apps.api.app.chat_contracts import (
    ChatMode,
    ChatRequest,
    ChatResponse,
    ConversationResponse,
)
from apps.api.app.conversations import (
    ConversationCapacityError,
    ConversationConflictError,
    ConversationNotFoundError,
    handle_conversation,
)
from apps.api.app.mcp_server.app import get_active_mcp_server


router = APIRouter(prefix="/api", tags=["chat"])


@asynccontextmanager
async def _open_business_tools(
    recorder: MCPCallRecorder | None = None,
) -> AsyncIterator[MCPBusinessTools]:
    """Open an in-process MCP session against the host application's server.

    ``recorder`` observes the real MCP tool calls made through this session so
    the browser can be shown the actual flow. It does not affect behavior.
    """
    server = get_active_mcp_server()
    async with InMemoryTransport(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield MCPClientBusinessTools(session, recorder=recorder)


_BUSINESS_ERROR_TYPES = (
    MCPBusinessToolError,
    InvalidAgentResultError,
    UnsupportedTransactionCapabilityError,
)


def _find_business_error(error: BaseException) -> BaseException | None:
    if isinstance(error, _BUSINESS_ERROR_TYPES):
        return error
    if isinstance(error, BaseExceptionGroup):
        for inner in error.exceptions:
            found = _find_business_error(inner)
            if found is not None:
                return found
    return None


def _unwrap_business_error(error: BaseException) -> BaseException:
    """Return the business error hidden inside an anyio ``ExceptionGroup``.

    The in-process MCP session runs inside a task group. A business error raised
    while the session body runs is re-raised wrapped in an ``ExceptionGroup``;
    unwrapping lets the chat boundary map it to the documented HTTP status.
    """
    if isinstance(error, BaseExceptionGroup):
        found = _find_business_error(error)
        if found is not None:
            return found
    return error


async def execute_chat(message: str) -> ChatResponse:
    """Parse a message, execute it through the existing runtime, and explain it.

    The real MCP tool calls made during execution are recorded and attached to
    the returned response (or, on failure, to the raised business error so the
    conversation's UNKNOWN result can still show what actually happened).
    """
    request = RequestUnderstanding().parse(message)
    recorder = MCPCallRecorder()

    try:
        async with _open_business_tools(recorder) as business_tools:
            runtime = AgentRuntime(
                TransactionOrchestrator(
                    ExecutionPlanPlanner(DeterministicPlannerProvider()),
                    business_tools,
                )
            )
            result: AgentResult = await runtime.execute(request)
    except BaseExceptionGroup as group:
        error = _unwrap_business_error(group)
        attach_events(error, recorder.events)
        raise error from group
    except BaseException as error:
        attach_events(error, recorder.events)
        raise

    return ChatResponse(
        **result.model_dump(),
        explanation=TransactionExplainer().explain(result),
        mcp_events=recorder.events,
    )


async def _handle_conversation(
    request: ChatRequest,
) -> ConversationResponse:
    """Advance the conversational boundary, mapping its errors to HTTP."""
    try:
        return await handle_conversation(
            message=request.message or "",
            conversation_id=request.conversation_id,
            executor=execute_chat,
            action=request.action.value if request.action is not None else None,
        )
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConversationConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ConversationCapacityError as error:
        # Transient capacity exhaustion: no conversation (and no transaction)
        # was created, so this is a retryable server condition, not a failure.
        raise HTTPException(status_code=503, detail=str(error)) from error
    except UnsupportedRequestError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except UnsupportedTransactionCapabilityError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/chat", response_model=ChatResponse | ConversationResponse)
async def chat(request: ChatRequest) -> ChatResponse | ConversationResponse:
    """Handle one message in either execution or conversation mode."""
    if request.mode == ChatMode.CONVERSATION:
        return await _handle_conversation(request)

    if request.conversation_id is not None:
        raise HTTPException(
            status_code=422,
            detail="conversation_id is only valid when mode is 'conversation'",
        )

    if request.action is not None:
        raise HTTPException(
            status_code=422,
            detail="action is only valid when mode is 'conversation'",
        )

    # In execute mode the request carries only a message, so it is present.
    assert request.message is not None
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
