"""Unit tests for the bounded in-memory conversation state machine."""

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest

from agent.orchestrator.service import (
    MCPBusinessToolError,
    UnsupportedTransactionCapabilityError,
)
from agent.request_understanding import RequestUnderstanding, UnsupportedRequestError
from agent.runtime.service import AgentResult
from apps.api.app.chat_contracts import ChatResponse, ConversationStep
from apps.api.app.conversations import (
    ConversationCapacityError,
    ConversationConflictError,
    ConversationNotFoundError,
    ConversationState,
    ConversationStore,
    handle_conversation,
)


COMPLETE_MESSAGE = "Buy ₦5,000 MTN airtime for 08030000001."

# The conversation layer renders the merged fields into a parser-safe canonical
# message before execution, so the executor receives this rather than the raw
# user turn. It parses back to the same amount, network, and beneficiary.
CANONICAL_MESSAGE = "Buy 5000.00 MTN airtime for 08030000001"


def success_response() -> ChatResponse:
    result = AgentResult(
        transaction_id=uuid4(),
        status="success",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000001",
        amount=Decimal("5000.00"),
        vendor_code="vendor_a",
        vendor_reference="VA-1",
        action="allow",
        reason=None,
        message="Transaction completed successfully",
        planner_candidate_vendor="vendor_a",
    )
    return ChatResponse(**result.model_dump(), explanation="completed successfully")


class RecordingExecutor:
    """Fake executor that records calls and can be made to raise."""

    def __init__(
        self,
        error: Exception | None = None,
        result: ChatResponse | None = None,
    ) -> None:
        self.calls: list[str] = []
        self._error = error
        self._result = result

    async def __call__(self, text: str) -> ChatResponse:
        self.calls.append(text)
        await asyncio.sleep(0)
        if self._error is not None:
            raise self._error
        if self._result is not None:
            return self._result
        return success_response()


def advance(
    store: ConversationStore,
    executor: RecordingExecutor,
    message: str,
    conversation_id: str | None,
):
    return asyncio.run(
        handle_conversation(
            message=message,
            conversation_id=conversation_id,
            executor=executor,
            store=store,
        )
    )


def test_collection_then_confirmation_without_execution():
    store = ConversationStore()
    executor = RecordingExecutor()

    first = advance(store, executor, "Buy ₦5,000 airtime.", None)
    assert first.step == ConversationStep.CLARIFY
    assert set(first.missing_fields) == {"network", "beneficiary"}

    second = advance(store, executor, "MTN", first.conversation_id)
    assert second.step == ConversationStep.CLARIFY
    assert second.missing_fields == ["beneficiary"]

    third = advance(store, executor, "08030000001", first.conversation_id)
    assert third.step == ConversationStep.CONFIRM
    assert third.result is None

    assert executor.calls == []


def test_amount_before_beneficiary_keeps_fields_separate():
    """Regression: amount and beneficiary supplied in separate turns must not merge.

    The reported bug joined every turn before parsing, so the amount "5000" and
    the beneficiary "08030000001" were read as one 15-digit beneficiary run and
    the amount was lost.
    """
    store = ConversationStore()
    executor = RecordingExecutor()

    body = advance(store, executor, "Buy airtime", None)
    conversation_id = body.conversation_id
    assert body.step == ConversationStep.CLARIFY
    assert set(body.missing_fields) == {"amount", "network", "beneficiary"}

    body = advance(store, executor, "MTN", conversation_id)
    assert body.step == ConversationStep.CLARIFY
    assert body.missing_fields == ["amount", "beneficiary"]
    assert body.draft.network == "MTN"

    body = advance(store, executor, "5000", conversation_id)
    assert body.step == ConversationStep.CLARIFY
    assert body.missing_fields == ["beneficiary"]
    assert body.draft.amount == Decimal("5000.00")

    body = advance(store, executor, "08030000001", conversation_id)
    assert body.step == ConversationStep.CONFIRM
    assert body.missing_fields == []
    assert body.draft.amount == Decimal("5000.00")
    assert body.draft.network == "MTN"
    assert body.draft.beneficiary == "08030000001"

    # The executor receives a representation that parses back exactly.
    completed = advance(store, executor, "confirm", conversation_id)
    assert completed.step == ConversationStep.COMPLETE
    assert completed.result.amount == Decimal("5000.00")
    assert completed.result.beneficiary == "08030000001"
    assert len(executor.calls) == 1
    parsed = RequestUnderstanding().parse(executor.calls[0])
    assert parsed.amount == Decimal("5000.00")
    assert parsed.network == "MTN"
    assert parsed.beneficiary == "08030000001"


def test_amount_after_network_order_also_confirms_correctly():
    """Control: the reverse field order must behave identically."""
    store = ConversationStore()
    executor = RecordingExecutor()

    body = advance(store, executor, "Buy airtime", None)
    conversation_id = body.conversation_id

    body = advance(store, executor, "5000", conversation_id)
    assert body.step == ConversationStep.CLARIFY
    assert body.missing_fields == ["network", "beneficiary"]
    assert body.draft.amount == Decimal("5000.00")

    body = advance(store, executor, "MTN", conversation_id)
    assert body.step == ConversationStep.CLARIFY

    body = advance(store, executor, "08030000001", conversation_id)
    assert body.step == ConversationStep.CONFIRM
    assert body.missing_fields == []
    assert body.draft.amount == Decimal("5000.00")
    assert body.draft.network == "MTN"
    assert body.draft.beneficiary == "08030000001"


def test_later_ambiguous_turn_does_not_clear_collected_fields():
    store = ConversationStore()
    executor = RecordingExecutor()

    body = advance(store, executor, "Buy airtime", None)
    conversation_id = body.conversation_id
    advance(store, executor, "5000", conversation_id)
    advance(store, executor, "MTN", conversation_id)

    # A turn that provides no new field must not erase what was already known.
    body = advance(store, executor, "please", conversation_id)
    assert body.step == ConversationStep.CLARIFY
    assert body.draft.amount == Decimal("5000.00")
    assert body.draft.network == "MTN"


def test_valid_correction_updates_previously_collected_field():
    store = ConversationStore()
    executor = RecordingExecutor()

    body = advance(store, executor, "Buy airtime", None)
    conversation_id = body.conversation_id
    advance(store, executor, "5000", conversation_id)
    advance(store, executor, "MTN", conversation_id)

    corrected = advance(store, executor, "7000", conversation_id)
    assert corrected.step == ConversationStep.CLARIFY
    assert corrected.draft.amount == Decimal("7000.00")

    body = advance(store, executor, "08030000009", conversation_id)
    assert body.step == ConversationStep.CONFIRM
    assert body.draft.amount == Decimal("7000.00")
    assert body.draft.beneficiary == "08030000009"

    completed = advance(store, executor, "confirm", conversation_id)
    assert completed.step == ConversationStep.COMPLETE
    parsed = RequestUnderstanding().parse(executor.calls[0])
    assert parsed.amount == Decimal("7000.00")
    assert parsed.beneficiary == "08030000009"


def test_spaced_beneficiary_is_preserved_across_separate_turns():
    store = ConversationStore()
    executor = RecordingExecutor()

    body = advance(store, executor, "Buy airtime", None)
    conversation_id = body.conversation_id
    advance(store, executor, "5000", conversation_id)
    advance(store, executor, "MTN", conversation_id)

    body = advance(store, executor, "0803 000 0001", conversation_id)
    assert body.step == ConversationStep.CONFIRM
    assert body.missing_fields == []
    assert body.draft.beneficiary == "08030000001"


def test_confirmation_executes_once_and_caches_result():
    store = ConversationStore()
    executor = RecordingExecutor()

    started = advance(store, executor, COMPLETE_MESSAGE, None)
    assert started.step == ConversationStep.CONFIRM

    completed = advance(store, executor, "confirm", started.conversation_id)
    assert completed.step == ConversationStep.COMPLETE
    assert completed.result is not None
    assert completed.result.status == "success"
    assert executor.calls == [CANONICAL_MESSAGE]


def test_repeated_confirmation_replays_cached_result():
    store = ConversationStore()
    executor = RecordingExecutor()

    started = advance(store, executor, COMPLETE_MESSAGE, None)
    first = advance(store, executor, "confirm", started.conversation_id)
    second = advance(store, executor, "yes", started.conversation_id)

    assert first.result.transaction_id == second.result.transaction_id
    assert executor.calls == [CANONICAL_MESSAGE]


def test_concurrent_confirmations_execute_at_most_once():
    store = ConversationStore()
    executor = RecordingExecutor()

    started = advance(store, executor, COMPLETE_MESSAGE, None)

    async def confirm_twice():
        return await asyncio.gather(
            handle_conversation(
                message="confirm",
                conversation_id=started.conversation_id,
                executor=executor,
                store=store,
            ),
            handle_conversation(
                message="confirm",
                conversation_id=started.conversation_id,
                executor=executor,
                store=store,
            ),
        )

    results = asyncio.run(confirm_twice())

    assert all(result.step == ConversationStep.COMPLETE for result in results)
    assert executor.calls == [CANONICAL_MESSAGE]


def test_cancellation_is_terminal_and_blocks_delayed_confirmation():
    store = ConversationStore()
    executor = RecordingExecutor()

    started = advance(store, executor, COMPLETE_MESSAGE, None)
    cancelled = advance(store, executor, "cancel", started.conversation_id)
    assert cancelled.step == ConversationStep.CANCELLED

    with pytest.raises(ConversationConflictError):
        advance(store, executor, "confirm", started.conversation_id)

    assert executor.calls == []


def test_unknown_conversation_id_is_rejected():
    store = ConversationStore()
    executor = RecordingExecutor()

    with pytest.raises(ConversationNotFoundError):
        advance(store, executor, "confirm", "missing")


def test_uncertain_execution_yields_unknown_without_retry():
    store = ConversationStore()
    executor = RecordingExecutor(error=MCPBusinessToolError("uncertain"))

    started = advance(store, executor, COMPLETE_MESSAGE, None)
    completed = advance(store, executor, "confirm", started.conversation_id)

    assert completed.step == ConversationStep.COMPLETE
    assert completed.result.status == "unknown"
    assert completed.result.transaction_id is None

    replay = advance(store, executor, "confirm", started.conversation_id)
    assert replay.result.status == "unknown"
    assert executor.calls == [CANONICAL_MESSAGE]


def test_pre_execution_error_resets_to_awaiting_confirmation():
    store = ConversationStore()
    failing = RecordingExecutor(error=UnsupportedTransactionCapabilityError("nope"))

    started = advance(store, failing, COMPLETE_MESSAGE, None)

    with pytest.raises(UnsupportedTransactionCapabilityError):
        advance(store, failing, "confirm", started.conversation_id)

    # The conversation is not stuck; a working executor can complete it.
    working = RecordingExecutor()
    completed = advance(store, working, "confirm", started.conversation_id)
    assert completed.step == ConversationStep.COMPLETE
    assert working.calls == [CANONICAL_MESSAGE]


def test_completed_conversation_rejects_a_different_request():
    store = ConversationStore()
    executor = RecordingExecutor()

    started = advance(store, executor, COMPLETE_MESSAGE, None)
    advance(store, executor, "confirm", started.conversation_id)

    with pytest.raises(ConversationConflictError):
        advance(store, executor, "Buy ₦9,000 airtime.", started.conversation_id)

    assert executor.calls == [CANONICAL_MESSAGE]


def test_new_conversations_receive_distinct_identifiers():
    store = ConversationStore()
    executor = RecordingExecutor()

    first = advance(store, executor, "Buy ₦5,000 airtime.", None)
    second = advance(store, executor, "Buy ₦5,000 airtime.", None)

    assert first.conversation_id != second.conversation_id


def unknown_response(transaction_id):
    result = AgentResult(
        transaction_id=transaction_id,
        status="unknown",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000001",
        amount=Decimal("5000.00"),
        vendor_code="vendor_a",
        vendor_reference=None,
        action="allow",
        reason=None,
        message="Transaction outcome is unknown",
        planner_candidate_vendor="vendor_a",
    )
    return ChatResponse(**result.model_dump(), explanation="outcome could not be confirmed")


def test_pre_side_effect_parser_error_resets_to_awaiting_confirmation():
    store = ConversationStore()
    failing = RecordingExecutor(error=UnsupportedRequestError("unsupported"))

    started = advance(store, failing, COMPLETE_MESSAGE, None)
    with pytest.raises(UnsupportedRequestError):
        advance(store, failing, "confirm", started.conversation_id)

    conversation = store._conversations[started.conversation_id]
    assert conversation.state is ConversationState.AWAITING_CONFIRMATION

    working = RecordingExecutor()
    completed = advance(store, working, "confirm", started.conversation_id)
    assert completed.step == ConversationStep.COMPLETE
    assert completed.result.status == "success"


def test_unexpected_execution_error_terminates_as_unknown_not_stuck():
    store = ConversationStore()
    failing = RecordingExecutor(error=RuntimeError("database unavailable"))

    started = advance(store, failing, COMPLETE_MESSAGE, None)
    completed = advance(store, failing, "confirm", started.conversation_id)

    assert completed.step == ConversationStep.COMPLETE
    assert completed.result is not None
    assert completed.result.status == "unknown"
    assert completed.result.transaction_id is None

    conversation = store._conversations[started.conversation_id]
    assert conversation.state is ConversationState.COMPLETE

    # A repeated confirmation replays the UNKNOWN outcome; it never re-executes
    # and is never stuck rejecting further turns as "already executing".
    replay = advance(store, failing, "confirm", started.conversation_id)
    assert replay.result.status == "unknown"
    assert failing.calls == [CANONICAL_MESSAGE]


def test_cancellation_during_execution_is_terminal_and_not_retried():
    store = ConversationStore()
    cancelling = RecordingExecutor(error=asyncio.CancelledError())

    started = advance(store, cancelling, COMPLETE_MESSAGE, None)
    with pytest.raises(asyncio.CancelledError):
        advance(store, cancelling, "confirm", started.conversation_id)

    conversation = store._conversations[started.conversation_id]
    assert conversation.state is ConversationState.COMPLETE
    assert conversation.result is not None
    assert conversation.result.status == "unknown"

    working = RecordingExecutor()
    replay = advance(store, working, "confirm", started.conversation_id)
    assert replay.result.status == "unknown"
    assert working.calls == []


def test_known_transaction_id_is_preserved_on_uncertain_result():
    store = ConversationStore()
    transaction_id = uuid4()
    executor = RecordingExecutor(result=unknown_response(transaction_id))

    started = advance(store, executor, COMPLETE_MESSAGE, None)
    completed = advance(store, executor, "confirm", started.conversation_id)

    assert completed.result.status == "unknown"
    assert completed.result.transaction_id == transaction_id

    replay = advance(store, executor, "confirm", started.conversation_id)
    assert replay.result.transaction_id == transaction_id
    assert executor.calls == [CANONICAL_MESSAGE]


def test_store_rejects_new_conversation_when_full_of_unresolved():
    store = ConversationStore(max_conversations=1)
    executor = RecordingExecutor()

    advance(store, executor, "Buy ₦5,000 airtime.", None)

    with pytest.raises(ConversationCapacityError):
        advance(store, executor, "Buy ₦9,000 airtime.", None)

    assert len(store._conversations) == 1


def test_store_does_not_evict_an_unresolved_terminal_conversation():
    store = ConversationStore(max_conversations=1)
    uncertain = RecordingExecutor(error=MCPBusinessToolError("uncertain"))

    started = advance(store, uncertain, COMPLETE_MESSAGE, None)
    advance(store, uncertain, "confirm", started.conversation_id)

    conversation = store._conversations[started.conversation_id]
    assert conversation.state is ConversationState.COMPLETE
    assert conversation.result.status == "unknown"

    with pytest.raises(ConversationCapacityError):
        advance(store, RecordingExecutor(), "Buy ₦9,000 airtime.", None)


def test_store_evicts_a_resolved_terminal_conversation_to_make_room():
    store = ConversationStore(max_conversations=1)
    executor = RecordingExecutor()

    started = advance(store, executor, COMPLETE_MESSAGE, None)
    advance(store, executor, "confirm", started.conversation_id)
    assert started.conversation_id in store._conversations

    second = advance(store, executor, "Buy ₦5,000 MTN airtime for 08030000002.", None)

    assert started.conversation_id not in store._conversations
    assert second.conversation_id in store._conversations
    assert len(store._conversations) == 1


def test_store_reaps_an_expired_resolved_conversation():
    store = ConversationStore(ttl_seconds=-1.0, max_conversations=10)
    executor = RecordingExecutor()

    started = advance(store, executor, COMPLETE_MESSAGE, None)
    advance(store, executor, "confirm", started.conversation_id)

    advance(store, executor, "Buy ₦9,000 airtime.", None)

    assert started.conversation_id not in store._conversations


def test_concurrent_confirmation_and_new_conversation_are_consistent():
    store = ConversationStore()
    executor = RecordingExecutor()

    started = advance(store, executor, COMPLETE_MESSAGE, None)

    async def exercise():
        return await asyncio.gather(
            handle_conversation(
                message="confirm",
                conversation_id=started.conversation_id,
                executor=executor,
                store=store,
            ),
            handle_conversation(
                message="confirm",
                conversation_id=started.conversation_id,
                executor=executor,
                store=store,
            ),
            handle_conversation(
                message="Buy ₦9,000 airtime.",
                conversation_id=None,
                executor=executor,
                store=store,
            ),
        )

    results = asyncio.run(exercise())

    confirmations = [result for result in results if result.step is ConversationStep.COMPLETE]
    assert len(confirmations) == 2
    assert confirmations[0].result.transaction_id == confirmations[1].result.transaction_id
    assert executor.calls == [CANONICAL_MESSAGE]


def test_first_clarification_is_friendly_and_asks_for_next_missing_field():
    store = ConversationStore()
    executor = RecordingExecutor()

    body = advance(store, executor, "Buy airtime", None)

    assert body.step == ConversationStep.CLARIFY
    assert body.prompt.startswith("Happy to help!")
    assert "How much airtime" in body.prompt


def test_clarification_acknowledges_newly_captured_network():
    store = ConversationStore()
    executor = RecordingExecutor()

    body = advance(store, executor, "Buy MTN airtime", None)

    assert body.step == ConversationStep.CLARIFY
    assert "MTN, got it!" in body.prompt
    assert "How much airtime" in body.prompt


def test_clarification_acknowledges_amount_and_asks_for_phone_number():
    store = ConversationStore()
    executor = RecordingExecutor()

    body = advance(store, executor, "Buy MTN airtime", None)
    body = advance(store, executor, "5000", body.conversation_id)

    assert body.step == ConversationStep.CLARIFY
    assert "₦5,000, got it!" in body.prompt
    assert "phone number" in body.prompt


def test_repeated_value_is_not_reacknowledged():
    store = ConversationStore()
    executor = RecordingExecutor()

    body = advance(store, executor, "Buy airtime", None)
    conversation_id = body.conversation_id
    advance(store, executor, "5000", conversation_id)

    repeated = advance(store, executor, "5000", conversation_id)

    assert repeated.step == ConversationStep.CLARIFY
    assert "got it!" not in repeated.prompt
    assert "mobile network" in repeated.prompt


def test_corrected_value_is_acknowledged():
    store = ConversationStore()
    executor = RecordingExecutor()

    body = advance(store, executor, "Buy airtime", None)
    conversation_id = body.conversation_id
    advance(store, executor, "5000", conversation_id)

    corrected = advance(store, executor, "7000", conversation_id)

    assert corrected.step == ConversationStep.CLARIFY
    assert "₦7,000, got it!" in corrected.prompt
    assert corrected.draft.amount == Decimal("7000.00")


def test_confirmation_prompt_summarizes_and_requests_explicit_confirmation():
    store = ConversationStore()
    executor = RecordingExecutor()

    body = advance(store, executor, COMPLETE_MESSAGE, None)

    assert body.step == ConversationStep.CONFIRM
    assert "₦5,000" in body.prompt
    assert "MTN" in body.prompt
    assert "08030000001" in body.prompt
    assert "Shall I go ahead?" in body.prompt


def test_ambiguous_reply_does_not_authorize_execution():
    store = ConversationStore()
    executor = RecordingExecutor()

    body = advance(store, executor, COMPLETE_MESSAGE, None)
    ambiguous = advance(store, executor, "maybe", body.conversation_id)

    assert ambiguous.step == ConversationStep.CONFIRM
    assert ambiguous.result is None
    assert executor.calls == []
