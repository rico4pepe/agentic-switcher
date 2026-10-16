"""Bounded, in-memory multi-turn airtime conversation state machine.

The conversation layer collects missing airtime fields across turns, asks for
explicit confirmation, and then delegates the single execution to the existing
:func:`execute_chat` pipeline. It never chooses a vendor, evaluates policy,
touches the transaction engine, or fabricates a transaction outcome.

Confirmation and cancellation are button-only. The browser sends an explicit
``action`` control signal, never free text, so a typed "yes", "ok", "confirm",
"go ahead", or "cancel" can never execute or cancel a transaction. While a
transaction awaits confirmation, any other input re-affirms the pending request
(reusing the exact same draft) instead of executing it, cancelling it, or
overwriting it. Input unrelated to a supported transaction is redirected to the
assistant's purpose without discarding collected details.

Guarantees are intentionally process-local: the store lives in memory, so
deduplication and terminal-state rules hold within a single process only. They
do not survive a restart and are not shared across workers (see ADR-007).
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from agent.explainer import TransactionExplainer
from agent.explainer.templates import format_amount
from agent.orchestrator.mcp_events import MCPToolCallEvent
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

# The explicit control actions a client may send. Confirmation and cancellation
# are button-only: free text is never interpreted as either, so a typed "yes",
# "ok", "confirm", "go ahead", or "cancel" can never execute or cancel anything.
CONFIRM_ACTION = "confirm"
CANCEL_ACTION = "cancel"
_CONTROL_ACTIONS = frozenset({CONFIRM_ACTION, CANCEL_ACTION})

# Shown whenever input arrives while a transaction is pending confirmation. It
# names both buttons, keeps the user in control, and states plainly that nothing
# has been submitted.
_CONFIRMATION_REQUIRED_PROMPT = (
    "Your transaction is ready for confirmation. Please press Confirm purchase "
    "to proceed, or Cancel to stop. No transaction has been submitted yet."
)

# Prepended when a turn is unrelated to a supported transaction and no
# confirmation is pending. It redirects to the assistant's supported purpose
# without inventing capabilities and without discarding collected details.
_OFF_TOPIC_PROMPT = (
    "I can only help with supported airtime purchases. "
)


@dataclass
class Conversation:
    """One bounded conversation and its serialization lock."""

    id: str
    state: ConversationState = ConversationState.COLLECTING
    turns: list[str] = field(default_factory=list)
    draft: ConversationDraft = field(default_factory=ConversationDraft)
    intent_present: bool = False
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
    action: str | None = None,
    store: ConversationStore | None = None,
) -> ConversationResponse:
    """Advance a conversation by one user turn and return the next turn.

    ``action`` is the explicit control channel used by the Confirm and Cancel
    buttons. It is never inferred from ``message``.
    """
    active_store = store or default_store
    conversation = await active_store.begin(conversation_id)
    try:
        async with conversation.lock:
            return await _advance(conversation, message, action, executor)
    finally:
        await active_store.end(conversation)


async def _advance(
    conversation: Conversation,
    message: str,
    action: str | None,
    executor: Executor,
) -> ConversationResponse:
    text = message.strip()

    if action is not None:
        if action not in _CONTROL_ACTIONS:
            raise ConversationConflictError(
                f"Unsupported conversation action: {action!r}"
            )
        return await _handle_action(conversation, action, executor)

    if conversation.state is ConversationState.COMPLETE:
        return _handle_completed(conversation, text)
    if conversation.state is ConversationState.CANCELLED:
        raise ConversationConflictError(
            "This conversation was cancelled and cannot be resumed"
        )
    if conversation.state is ConversationState.EXECUTING:
        raise ConversationConflictError("This conversation is already executing")

    if conversation.state is ConversationState.AWAITING_CONFIRMATION:
        # Button-only confirmation: no typed message executes, cancels, or
        # overwrites the pending transaction. The same pending request is
        # returned unchanged, with an explicit instruction to use the buttons.
        return _confirmation_required_response(conversation)

    return _collect(conversation, text)


async def _handle_action(
    conversation: Conversation,
    action: str,
    executor: Executor,
) -> ConversationResponse:
    """Apply an explicit button action to a non-terminal conversation.

    ``CONFIRM`` executes only a transaction that is actually awaiting
    confirmation, so a stray or duplicate confirmation cannot execute anything
    that is not pending. ``CANCEL`` ends the conversation without ever executing.
    """
    if conversation.state is ConversationState.COMPLETE:
        if action == CONFIRM_ACTION:
            # Duplicate confirmation of an already-decided conversation: replay
            # the cached outcome. This never re-executes.
            return _completed_response(conversation)
        raise ConversationConflictError("This conversation is already complete")
    if conversation.state is ConversationState.CANCELLED:
        raise ConversationConflictError(
            "This conversation was cancelled and cannot be resumed"
        )
    if conversation.state is ConversationState.EXECUTING:
        raise ConversationConflictError("This conversation is already executing")

    if action == CANCEL_ACTION:
        return _cancel(conversation)

    if conversation.state is not ConversationState.AWAITING_CONFIRMATION:
        raise ConversationConflictError(
            "There is no pending transaction to confirm"
        )
    return await _execute(conversation, executor)


def _handle_completed(conversation: Conversation, text: str) -> ConversationResponse:
    if _restates_finalized(conversation, text):
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

    incoming = inspect_request(text)
    previous = conversation.draft
    conversation.draft = _merge_draft(previous, incoming)
    if incoming.intent_present:
        conversation.intent_present = True

    requirements = _merged_requirements(
        conversation.draft, conversation.intent_present
    )

    if requirements.complete is not None:
        conversation.finalized_text = _canonical_text(conversation.draft)
        conversation.state = ConversationState.AWAITING_CONFIRMATION
        return _confirmation_response(conversation, requirements)

    conversation.state = ConversationState.COLLECTING
    return _clarification_response(
        conversation,
        requirements,
        previous=previous,
        is_first_turn=len(conversation.turns) == 1,
        off_topic=_turn_is_off_topic(incoming),
    )


def _turn_is_off_topic(incoming: RequestRequirements) -> bool:
    """Whether a turn relates to no supported transaction at all.

    A turn is off topic only when it neither asks to purchase (no intent) nor
    supplies any parser-recognized transaction field. A terse but relevant reply
    such as ``MTN``, ``5000``, or a phone number is never off topic, so valid
    details are never discarded as small talk. The collected draft is untouched
    either way.
    """
    return not (
        incoming.intent_present
        or incoming.product is not None
        or incoming.amount is not None
        or incoming.network is not None
        or incoming.beneficiary is not None
    )


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
    except Exception as error:
        # Everything else may have happened before or after the vendor
        # submission: the existing MCP error contract reports both as an opaque
        # tool error and never returns the persisted transaction identity. Since
        # the side-effect state cannot be proven, never retry; record a truthful
        # UNKNOWN outcome and keep the conversation terminal. Any real MCP calls
        # that were made are carried on the error and surfaced truthfully.
        conversation.result = _uncertain_result(
            conversation,
            mcp_events=_attached_events(error),
        )
        conversation.state = ConversationState.COMPLETE
        return _completed_response(conversation)
    except BaseException as error:
        # Cancellation or interpreter shutdown while the outcome is unknown.
        # Terminate truthfully (never left stuck in EXECUTING, never retried)
        # and then propagate.
        conversation.result = _uncertain_result(
            conversation,
            mcp_events=_attached_events(error),
        )
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
        prompt="No problem, I've cancelled that. No purchase was made.",
        missing_fields=[],
        draft=None,
        result=None,
    )


def _clarification_response(
    conversation: Conversation,
    requirements: RequestRequirements,
    *,
    previous: ConversationDraft,
    is_first_turn: bool,
    off_topic: bool = False,
) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=conversation.id,
        step=ConversationStep.CLARIFY,
        prompt=_clarification_prompt(
            requirements,
            previous,
            conversation.draft,
            is_first_turn=is_first_turn,
            off_topic=off_topic,
        ),
        missing_fields=list(requirements.missing_fields),
        draft=conversation.draft,
        result=None,
    )


def _confirmation_required_response(
    conversation: Conversation,
) -> ConversationResponse:
    """Re-affirm a pending confirmation after unexpected input.

    The step stays ``CONFIRM`` and the draft is returned unchanged, so the
    pending transaction, its summary, and both buttons remain intact. Nothing is
    executed, cancelled, or overwritten.
    """
    return ConversationResponse(
        conversation_id=conversation.id,
        step=ConversationStep.CONFIRM,
        prompt=_CONFIRMATION_REQUIRED_PROMPT,
        missing_fields=[],
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


def _attached_events(error: BaseException) -> list[MCPToolCallEvent]:
    """Return the real MCP events carried on a failed execution, if any."""
    events = getattr(error, "mcp_events", None)
    if isinstance(events, list):
        return events
    return []


def _uncertain_result(
    conversation: Conversation,
    *,
    mcp_events: Sequence[MCPToolCallEvent] = (),
) -> ChatResponse:
    """Build a truthful UNKNOWN result for an execution failure of unknown cause.

    The known request fields come from the authoritative parser. The outcome is
    explicitly ``unknown`` (never ``failed`` or ``success``). No transaction
    identifier is invented: the existing MCP error contract does not surface the
    persisted transaction identity, so none is available here. Any MCP calls
    that really happened before the failure are reported as-is.
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
        mcp_events=list(mcp_events),
    )


def _merge_draft(
    current: ConversationDraft,
    incoming: RequestRequirements,
) -> ConversationDraft:
    """Merge newly parsed fields into the collected draft.

    Only fields the incoming turn actually provides are replaced, so a later
    partial or ambiguous turn never clears an earlier valid value. A new value
    for a field (for example a corrected amount) replaces the previous one. The
    amount and beneficiary come from independent parses of the incoming turn and
    are never combined into one another.
    """
    product = (
        incoming.product if incoming.product is not None else current.product_type
    )
    network = incoming.network if incoming.network is not None else current.network
    beneficiary = (
        incoming.beneficiary
        if incoming.beneficiary is not None
        else current.beneficiary
    )
    amount = incoming.amount if incoming.amount is not None else current.amount
    return ConversationDraft(
        service_type=product,
        product_type=product,
        network=network,
        beneficiary=beneficiary,
        amount=amount,
    )


def _merged_requirements(
    draft: ConversationDraft,
    intent_present: bool,
) -> RequestRequirements:
    """Report the remaining fields for the merged draft.

    The authoritative parser is only invoked once every field is present, so a
    complete request is validated by exactly the same code path as the legacy
    boundary.
    """
    missing_fields = tuple(
        name
        for name, present in (
            ("intent", intent_present),
            ("product", draft.product_type is not None),
            ("amount", draft.amount is not None),
            ("network", draft.network is not None),
            ("beneficiary", draft.beneficiary is not None),
        )
        if not present
    )

    complete = None
    if not missing_fields:
        complete = RequestUnderstanding().parse(_canonical_text(draft))

    return RequestRequirements(
        intent_present=intent_present,
        product=draft.product_type,
        amount=draft.amount,
        network=draft.network,
        beneficiary=draft.beneficiary,
        missing_fields=missing_fields,
        complete=complete,
    )


def _canonical_text(draft: ConversationDraft) -> str:
    """Render the merged fields as a message the parser reads back exactly.

    The network and product tokens sit between the amount and the beneficiary,
    so the parser can never merge the two numeric values into one digit run.
    Called only when the draft is complete, so every field is present.
    """
    return (
        f"Buy {draft.amount} {draft.network} {draft.product_type} "
        f"for {draft.beneficiary}"
    )


def _confirmation_prompt(request: AgentRequest) -> str:
    network = f"{request.network} " if request.network else ""
    product = request.product_type.replace("_", " ").lower()
    return (
        "Perfect, I've got those details. Please review your transaction: "
        f"{format_amount(request.amount)} {network}{product} "
        f"for {request.beneficiary}. Shall I go ahead?"
    )


_NEXT_FIELD_QUESTIONS: dict[str, str] = {
    "intent": "What would you like to do? (for example, buy airtime)",
    "product": "Which product would you like? (for example, airtime)",
    "amount": "How much airtime would you like to buy?",
    "network": "Which mobile network would you like to recharge?",
    "beneficiary": "Which phone number should receive the airtime?",
}


def _clarification_prompt(
    requirements: RequestRequirements,
    previous: ConversationDraft,
    current: ConversationDraft,
    *,
    is_first_turn: bool,
    off_topic: bool = False,
) -> str:
    """Acknowledge only newly captured fields, then ask for the next missing one.

    The next field asked for is driven entirely by the parser's own field
    detection (``requirements.missing_fields`` follows ``MISSING_ORDER``), so
    the question adapts to whatever is still unknown rather than a fixed script.
    An off-topic turn adds a redirect to the supported purpose but keeps the
    collected draft and the next-field question, so the conversation continues.
    """
    missing = requirements.missing_fields
    question = (
        _NEXT_FIELD_QUESTIONS.get(
            missing[0], "Could you share the remaining details?"
        )
        if missing
        else "Please provide the purchase details."
    )

    parts: list[str] = []
    acknowledged = _newly_captured_values(previous, current)
    if acknowledged:
        parts.append(f"{_join_values(acknowledged)}, got it!")
    elif is_first_turn:
        parts.append("Happy to help!")
    parts.append(question)
    prompt = " ".join(parts)
    if off_topic:
        return f"{_OFF_TOPIC_PROMPT}{prompt}"
    return prompt


def _newly_captured_values(
    previous: ConversationDraft,
    current: ConversationDraft,
) -> list[str]:
    """Value strings for fields this turn actually captured (or corrected).

    A field is reported only when the merged draft differs from the draft that
    existed before the turn, so a repeated/ambiguous turn never re-acknowledges
    a value the user already gave.
    """
    values: list[str] = []
    if current.network is not None and current.network != previous.network:
        values.append(current.network)
    if current.amount is not None and current.amount != previous.amount:
        values.append(format_amount(current.amount))
    if (
        current.beneficiary is not None
        and current.beneficiary != previous.beneficiary
    ):
        values.append(current.beneficiary)
    return values


def _join_values(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return ", ".join(values[:-1]) + f", and {values[-1]}"
