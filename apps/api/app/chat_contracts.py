"""HTTP request/response contracts for the chat and conversation boundaries.

These models describe exactly what the browser may send and receive. Legacy
clients use ``mode="execute"`` (the default) and retain the original
:class:`ChatResponse` shape. Conversational clients opt in with
``mode="conversation"`` and receive :class:`ConversationResponse`, which never
reuses transaction result fields to describe an in-progress conversation.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.orchestrator.mcp_events import MCPToolCallEvent
from agent.runtime.service import AgentResult


class ChatMode(StrEnum):
    """How a client wants ``POST /api/chat`` to interpret its message."""

    EXECUTE = "execute"
    CONVERSATION = "conversation"


class ChatAction(StrEnum):
    """An explicit, button-only control signal for an in-progress conversation.

    Confirmation and cancellation are never inferred from free text. The browser
    emits one of these only when the user presses the matching button, so typed
    affirmatives (``yes``, ``ok``, ``confirm``, ...) can never execute or cancel
    a transaction. The backend validates the action against the conversation's
    actual state.
    """

    CONFIRM = "confirm"
    CANCEL = "cancel"


class ChatRequest(BaseModel):
    """The bounded input a browser may supply.

    A normal turn carries a natural-language ``message``. A control turn carries
    an ``action`` and (for conversation mode) a ``conversation_id`` instead; the
    two are mutually exclusive so free text can never masquerade as a control
    signal.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str | None = Field(default=None, max_length=1000)
    mode: ChatMode = ChatMode.EXECUTE
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)
    action: ChatAction | None = None

    @model_validator(mode="after")
    def _require_message_or_action(self) -> "ChatRequest":
        if self.action is None:
            if not self.message:
                raise ValueError("a message is required unless an action is given")
            return self
        if self.message:
            raise ValueError("message must not be sent together with an action")
        if self.mode is not ChatMode.CONVERSATION:
            raise ValueError("action is only valid when mode is 'conversation'")
        if self.conversation_id is None:
            raise ValueError("action requires a conversation_id")
        return self


class ChatResponse(AgentResult):
    """Authoritative agent result plus its deterministic explanation.

    ``mcp_events`` lists the real MCP tool calls made while producing this
    result, in order. It is empty when no MCP tool was called (for example a
    policy denial still calls capability discovery, so it is never fabricated
    from scenario or status). Values are sanitized at the MCP boundary.
    """

    explanation: str
    mcp_events: list[MCPToolCallEvent] = Field(default_factory=list)


class ConversationStep(StrEnum):
    """The bounded set of conversation states surfaced to the browser."""

    CLARIFY = "clarify"
    CONFIRM = "confirm"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


class ConversationDraft(BaseModel):
    """The fields collected so far. Values are only ever parser-derived."""

    model_config = ConfigDict(extra="forbid")

    service_type: str | None = None
    product_type: str | None = None
    network: str | None = None
    beneficiary: str | None = None
    amount: Decimal | None = None


class ConversationResponse(BaseModel):
    """A conversation turn.

    ``result`` is the only place an authoritative transaction outcome appears;
    it is ``None`` until execution completes. Conversation progress is never
    encoded as a transaction ``status`` or ``action``.
    """

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    step: ConversationStep
    prompt: str
    missing_fields: list[str]
    draft: ConversationDraft | None = None
    result: ChatResponse | None = None
