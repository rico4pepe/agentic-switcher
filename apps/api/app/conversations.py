"""Bounded, in-memory multi-turn airtime conversation state machine.

The conversation layer collects missing airtime fields across turns, asks for
explicit confirmation, and then delegates the single execution to the existing
:func:`execute_chat` pipeline. It never chooses a vendor, evaluates policy,
touches the transaction engine, or fabricates a transaction outcome.

Guarantees are intentionally process-local: the store lives in memory, so
deduplication and terminal-state rules hold within a single process only. They
do not survive a restart and are not shared across workers (see ADR-007).
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from agent.explainer import TransactionExplainer
from agent.explainer.templates import format_amount
from agent.orchestrator.service import UnsupportedTransactionCapabilityError
from agent.request_requirements import RequestRequirements, inspect_request
from agent.request_understanding import RequestUnderstanding, UnsupportedRequestError
from agent.runtime.service import AgentRequest, AgentResult
from apps.api.app.chat_contracts import (
    ChatResponse,
    ConversationDraft,
    ConversationResponse,
    ConversationStep,
)

# The executor is the existing chat pipeline: text in, authoritative result out.
Executor = Callable[[str], Awaitable[ChatResponse]]


class ConversationNotFoundError(LookupError):
    """Raised when a conversation identifier is unknown or expired."""


class ConversationConflictError(RuntimeError):
    """Raised when a request cannot be applied to a conversation's state."""


class ConversationCapacityError(RuntimeError):
    """Raised when no new conversation can be created within the store bound."""


class ConversationState(StrEnum):
    """Internal conversation lifecycle."""

    COLLECTING = "collecting"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


_TERMINAL_STATES = frozenset({ConversationState.COMPLETE, ConversationState.CANCELLED})

_AFFIRMATIVE = frozenset(
    {
        "yes",
        "y",
        "yeah",
        "yep",
        "confirm",
        "confirmed",
        "proceed",
        "ok",
        "okay",
        "go",
        "go ahead",
        "approve",
        "buy",
        "sure",
    }
)
_NEGATIVE = frozenset(
    {
        "no",
        "n",
        "nope",
        "cancel",
        "stop",
        "abort",
        "never mind",
        "nevermind",
        "nvm",
        "don't",
        "do not",
    }
)


@dataclass
class Conversation:
    """One bounded conversation and its serialization lock."""

    id: str
    state: ConversationState = ConversationState.COLLECTING
    turns: list[str] = field(default_factory=list)
    draft: ConversationDraft = field(default_factory=ConversationDraft)
    finalized_text: str | None = None
    result: ChatResponse | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active: int = 0
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES


class ConversationStore:
    """Strictly bounded in-memory registry that never evicts an in-use or
    unresolved conversation.

    Each conversation owns its own :class:`asyncio.Lock`. The registry lock is
    held only long enough to look up or create an entry, to adjust its
    ``active`` reference count, and to evict an eligible entry, so a
    conversation is never removed while a request holds a reference to it.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 1800.0,
        max_conversations: int = 200,
    ) -> None:
        self._registry_lock = asyncio.Lock()
        self._conversations: OrderedDict[str, Conversation] = OrderedDict()
        self._ttl_seconds = ttl_seconds
        self._max_conversations = max_conversations

    async def begin(self, conversation_id: str | None) -> Conversation:
        async with self._registry_lock:
            if conversation_id:
                conversation = self._conversations.get(conversation_id)
                if conversation is None:
                    raise ConversationNotFoundError(
                        f"Conversation {conversation_id!r} was not found or has expired"
                    )
                conversation.active += 1
                conversation.updated_at = time.monotonic()
                self._conversations.move_to_end(conversation_id)
                return conversation

            self._reap_expired_locked()
            if len(self._conversations) >= self._max_conversations and not (
                self._evict_one_locked()
            ):
                raise ConversationCapacityError(
                    "The conversation store is at capacity and no eligible "
                    "conversation can be evicted"
                )

            conversation = Conversation(id=str(uuid4()))
            self._conversations[conversation.id] = conversation
            conversation.active += 1
            return conversation

    async def end(self, conversation: Conversation) -> None:
        async with self._registry_lock:
            if conversation.active > 0:
                conversation.active -= 1
            conversation.updated_at = time.monotonic()
            self._reap_expired_locked()

    def clear(self) -> None:
        """Drop all conversations. Intended for test isolation."""
        self._conversations.clear()

    @staticmethod
    def _is_evictable(conversation: Conversation) -> bool:
        """Whether a conversation may be dropped without losing information.

        Only idle, fully resolved conversations are evictable:

        - ``active > 0`` means a request is using it right now.
        - A non-terminal state may still lead to an execution.
        - A ``COMPLETE`` conversation whose outcome is ``unknown`` may still
          need its cached state for the user and for investigation, so it is
          retained even after the TTL.
        """
        if conversation.active > 0 or not conversation.is_terminal:
            return False
        if conversation.state is ConversationState.COMPLETE:
            result = conversation.result
            if result is None or result.status == "unknown":
                return False
        return True

    def _reap_expired_locked(self) -> None:
        now = time.monotonic()
        for conversation_id in list(self._conversations):
            conversation = self._conversations[conversation_id]
            if (
                self._is_evictable(conversation)
                and now - conversation.updated_at > self._ttl_seconds
            ):
                del self._conversations[conversation_id]

    def _evict_one_locked(self) -> bool:
        for conversation_id in list(self._conversations):
            if self._is_evictable(self._conversations[conversation_id]):
                del self._conversations[conversation_id]
                return True
        return False


default_store = ConversationStore()


def reset_conversations() -> None:
    """Clear the default store. Intended for test isolation."""
    default_store.clear()


async def handle_conversation(
    *,
    message: str,
    conversation_id: str | None,
    executor: Executor,
    store: ConversationStore | None = None,
) -> ConversationResponse:
    """Advance a conversation by one user message and return the next turn."""
    active_store = store or default_store
    conversation = await active_store.begin(conversation_id)
    try:
        async with conversation.lock:
            return await _advance(conversation, message, executor)
    finally:
        await active_store.end(conversation)


async def _advance(
    conversation: Conversation,
    message: str,
    executor: Executor,
) -> ConversationResponse:
    text = message.strip()

    if conversation.state is ConversationState.COMPLETE:
        return _handle_completed(conversation, text)
    if conversation.state is ConversationState.CANCELLED:
        raise ConversationConflictError(
            "This conversation was cancelled and cannot be resumed"
        )
    if conversation.state is ConversationState.EXECUTING:
        raise ConversationConflictError("This conversation is already executing")

    if conversation.state is ConversationState.AWAITING_CONFIRMATION:
        if _is_negative(text):
            return _cancel(conversation)
        if _is_affirmative(text):
            return await _execute(conversation, executor)
        # Anything else is treated as additional information for the request.
    elif _is_negative(text):
        return _cancel(conversation)

    return _collect(conversation, text)


def _handle_completed(conversation: Conversation, text: str) -> ConversationResponse:
    if _is_affirmative(text) or _restates_finalized(conversation, text):
        return _completed_response(conversation)
    raise ConversationConflictError(
        "This conversation is already complete; start a new conversation "
        "for a different purchase"
    )


def _restates_finalized(conversation: Conversation, text: str) -> bool:
    if not conversation.finalized_text:
        return False
    return text.casefold() == conversation.finalized_text.strip().casefold()


def _collect(conversation: Conversation, text: str) -> ConversationResponse:
    conversation.turns.append(text)
    combined = " ".join(conversation.turns)
    requirements = inspect_request(combined)
    conversation.draft = _draft_from_requirements(requirements)

    if requirements.complete is not None:
        conversation.finalized_text = combined
        conversation.state = ConversationState.AWAITING_CONFIRMATION
        return _confirmation_response(conversation, requirements)

    conversation.state = ConversationState.COLLECTING
    return _clarification_response(conversation, requirements)


# Errors raised only *before* any vendor side effect is possible: the parser
# rejected the text, or capability discovery returned nothing executable. Both
# happen before the MCP execution tool is ever called, so a confirmed request
# may safely be revised and confirmed again after these.
_PRE_SIDE_EFFECT_ERRORS = (
    UnsupportedRequestError,
    UnsupportedTransactionCapabilityError,
)


async def _execute(
    conversation: Conversation,
    executor: Executor,
) -> ConversationResponse:
    if not conversation.finalized_text:
        raise ConversationConflictError("There is no confirmed request to execute")

    conversation.state = ConversationState.EXECUTING
    try:
        result = await executor(conversation.finalized_text)
    except _PRE_SIDE_EFFECT_ERRORS:
        # Deterministic rejection before execution begins. No vendor side effect
        # occurred, so reset to await a revised confirmation and surface the
        # error (the caller maps it to a client error, never to UNKNOWN).
        conversation.state = ConversationState.AWAITING_CONFIRMATION
        raise
    except Exception:
        # Everything else may have happened before or after the vendor
        # submission: the existing MCP error contract reports both as an opaque
        # tool error and never returns the persisted transaction identity. Since
        # the side-effect state cannot be proven, never retry; record a truthful
        # UNKNOWN outcome and keep the conversation terminal.
        conversation.result = _uncertain_result(conversation)
        conversation.state = ConversationState.COMPLETE
        return _completed_response(conversation)
    except BaseException:
        # Cancellation or interpreter shutdown while the outcome is unknown.
        # Terminate truthfully (never left stuck in EXECUTING, never retried)
        # and then propagate.
        conversation.result = _uncertain_result(conversation)
        conversation.state = ConversationState.COMPLETE
        raise

    conversation.result = result
    conversation.state = ConversationState.COMPLETE
    return _completed_response(conversation)


def _cancel(conversation: Conversation) -> ConversationResponse:
    conversation.state = ConversationState.CANCELLED
    conversation.result = None
    return ConversationResponse(
        conversation_id=conversation.id,
        step=ConversationStep.CANCELLED,
        prompt="Cancelled. No purchase was made.",
        missing_fields=[],
        draft=None,
        result=None,
    )


def _clarification_response(
    conversation: Conversation,
    requirements: RequestRequirements,
) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=conversation.id,
        step=ConversationStep.CLARIFY,
        prompt=_clarification_prompt(requirements),
        missing_fields=list(requirements.missing_fields),
        draft=conversation.draft,
        result=None,
    )


def _confirmation_response(
    conversation: Conversation,
    requirements: RequestRequirements,
) -> ConversationResponse:
    request = requirements.complete
    assert request is not None  # only called when the request is complete
    return ConversationResponse(
        conversation_id=conversation.id,
        step=ConversationStep.CONFIRM,
        prompt=_confirmation_prompt(request),
        missing_fields=[],
        draft=conversation.draft,
        result=None,
    )


def _completed_response(conversation: Conversation) -> ConversationResponse:
    if conversation.result is None:
        raise ConversationConflictError("This conversation has no result to return")
    return ConversationResponse(
        conversation_id=conversation.id,
        step=ConversationStep.COMPLETE,
        prompt=conversation.result.explanation,
        missing_fields=[],
        draft=conversation.draft,
        result=conversation.result,
    )


def _uncertain_result(conversation: Conversation) -> ChatResponse:
    """Build a truthful UNKNOWN result for an execution failure of unknown cause.

    The known request fields come from the authoritative parser. The outcome is
    explicitly ``unknown`` (never ``failed`` or ``success``). No transaction
    identifier is invented: the existing MCP error contract does not surface the
    persisted transaction identity, so none is available here.
    """
    request = None
    if conversation.finalized_text:
        request = inspect_request(conversation.finalized_text).complete
        if request is None:
            request = RequestUnderstanding().parse(conversation.finalized_text)
    if request is None:
        raise ConversationConflictError("There is no confirmed request to execute")

    result = AgentResult(
        transaction_id=None,
        status="unknown",
        service_type=request.service_type,
        product_type=request.product_type,
        network=request.network,
        beneficiary=request.beneficiary,
        amount=request.amount,
        vendor_code=None,
        vendor_reference=None,
        action="allow",
        reason=None,
        message="Transaction outcome could not be confirmed",
        planner_candidate_vendor=None,
    )
    return ChatResponse(
        **result.model_dump(),
        explanation=TransactionExplainer().explain(result),
    )


def _draft_from_requirements(requirements: RequestRequirements) -> ConversationDraft:
    product = requirements.product
    return ConversationDraft(
        service_type=product,
        product_type=product,
        network=requirements.network,
        beneficiary=requirements.beneficiary,
        amount=requirements.amount,
    )


def _confirmation_prompt(request: AgentRequest) -> str:
    network = f"{request.network} " if request.network else ""
    return (
        f"Confirm: buy {format_amount(request.amount)} {network}airtime "
        f"for {request.beneficiary}?"
    )


def _clarification_prompt(requirements: RequestRequirements) -> str:
    missing = requirements.missing_fields
    if not missing:
        return "Please provide the purchase details."

    labels: list[str] = []
    if "intent" in missing:
        labels.append("what you would like to do (for example, buy airtime)")
    if "product" in missing:
        labels.append("the product (airtime)")
    if "amount" in missing:
        labels.append("the amount")
    if "network" in missing:
        labels.append("the network")
    if "beneficiary" in missing:
        labels.append("the beneficiary phone number")
    return f"To continue, please provide {_join_labels(labels)}."


def _join_labels(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def _normalize(text: str) -> str:
    return " ".join(text.strip().casefold().split()).strip(".!?")


def _is_affirmative(text: str) -> bool:
    return _normalize(text) in _AFFIRMATIVE


def _is_negative(text: str) -> bool:
    return _normalize(text) in _NEGATIVE
