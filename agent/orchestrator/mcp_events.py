"""Truthful MCP tool-call events surfaced to the browser.

The MCP activity panel renders *actual* MCP tool invocations, so this module is
the smallest reliable instrumentation: a per-request :class:`MCPCallRecorder`
that the MCP client boundary appends to, plus a sanitized wire model
(:class:`MCPToolCallEvent`).

Events are attached to the existing ``POST /api/chat`` response
(:attr:`apps.api.app.chat_contracts.ChatResponse.mcp_events`), so no new
transport (WebSocket, SSE) or dependency is needed. A tool that was registered
or merely available is never recorded: only a real ``tools/call`` appends an
event.

Sanitization happens here, at the boundary, so API keys, credentials,
idempotency keys and unnecessary personal data never leave the backend.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Keys whose values are never useful to a judge and must never be exposed.
SENSITIVE_KEYS = frozenset(
    {
        "idempotency_key",
        "api_key",
        "api_secret",
        "authorization",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "password",
        "credential",
        "credentials",
        "raw_vendor_response",
        "raw_response",
    }
)

# Keys whose values are personal data and are masked rather than shown whole.
PERSONAL_KEYS = frozenset(
    {"beneficiary", "msisdn", "phone", "phone_number", "account_number"}
)

REDACTED = "[redacted]"


class MCPToolCallEvent(BaseModel):
    """One real MCP tool invocation, sanitized for display."""

    model_config = ConfigDict(extra="forbid")

    sequence: int
    tool: str
    status: Literal["succeeded", "failed"]
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float | None = None
    transaction_id: str | None = None


def mask_personal(value: str) -> str:
    """Mask a personal identifier such as a phone number.

    Keeps the first three and last two characters so a judge can still tell two
    numbers apart without exposing the whole value.
    """
    if len(value) <= 5:
        return "*" * len(value)
    return f"{value[:3]}{'*' * (len(value) - 5)}{value[-2:]}"


def _jsonable(value: object) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal | UUID):
        return str(value)
    return str(value)


def _sanitize_item(value: object) -> Any:
    if isinstance(value, Mapping):
        return sanitize_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_sanitize_item(item) for item in value]
    return _jsonable(value)


def sanitize_mapping(mapping: Mapping[object, object]) -> dict[str, Any]:
    """Return a JSON-safe copy with secrets redacted and personal data masked.

    Sanitization is recursive and key-driven: any key in :data:`SENSITIVE_KEYS`
    is replaced wholesale, and any key in :data:`PERSONAL_KEYS` is masked.
    """
    sanitized: dict[str, Any] = {}
    for key, value in mapping.items():
        name = str(key)
        if name in SENSITIVE_KEYS:
            sanitized[name] = REDACTED
        elif isinstance(value, str) and name in PERSONAL_KEYS:
            sanitized[name] = mask_personal(value)
        else:
            sanitized[name] = _sanitize_item(value)
    return sanitized


@dataclass
class MCPCallRecorder:
    """Collect the real MCP tool calls made during a single request.

    A fresh recorder is created per ``/api/chat`` request, so retries or
    repeated requests cannot duplicate events.
    """

    events: list[MCPToolCallEvent] = field(default_factory=list)

    def record(
        self,
        *,
        tool: str,
        arguments: Mapping[object, object],
        status: Literal["succeeded", "failed"],
        result: Mapping[object, object] | None = None,
        error: str | None = None,
        duration_ms: float | None = None,
    ) -> MCPToolCallEvent:
        """Append one event. Never raises: recording must not break a call."""
        try:
            sanitized_result = sanitize_mapping(result) if result is not None else None
            transaction_id: str | None = None
            if sanitized_result is not None:
                candidate = sanitized_result.get("transaction_id")
                if candidate is not None:
                    transaction_id = str(candidate)
            event = MCPToolCallEvent(
                sequence=len(self.events) + 1,
                tool=tool,
                status=status,
                arguments=sanitize_mapping(arguments),
                result=sanitized_result,
                error=error,
                duration_ms=duration_ms,
                transaction_id=transaction_id,
            )
        except Exception:  # pragma: no cover - defensive; never block a call
            return MCPToolCallEvent(
                sequence=len(self.events) + 1,
                tool=tool,
                status=status,
                arguments={},
                result=None,
                error=error,
                duration_ms=duration_ms,
                transaction_id=None,
            )
        self.events.append(event)
        return event


def attach_events(
    error: BaseException,
    events: Sequence[MCPToolCallEvent],
) -> None:
    """Carry recorded events on a raised error.

    The conversation boundary turns an execution failure into a truthful
    ``UNKNOWN`` result; attaching the real events to the error lets that result
    still show what actually happened, instead of losing the evidence.
    """
    try:
        error.mcp_events = list(events)  # type: ignore[attr-defined]
    except (AttributeError, TypeError):  # pragma: no cover - defensive
        pass
