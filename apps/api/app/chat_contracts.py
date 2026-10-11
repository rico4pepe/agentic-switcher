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

from pydantic import BaseModel, ConfigDict, Field

from agent.runtime.service import AgentResult


class ChatMode(StrEnum):
    """How a client wants ``POST /api/chat`` to interpret its message."""

    EXECUTE = "execute"
    CONVERSATION = "conversation"


class ChatRequest(BaseModel):
    """The only input a browser may supply: a message and a mode."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=1000)
    mode: ChatMode = ChatMode.EXECUTE
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)


class ChatResponse(AgentResult):
    """Authoritative agent result plus its deterministic explanation."""

    explanation: str


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
