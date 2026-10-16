"""Tests for truthful MCP call recording and boundary sanitization."""

from decimal import Decimal
from uuid import UUID

from agent.orchestrator.mcp_events import (
    REDACTED,
    MCPCallRecorder,
    attach_events,
    mask_personal,
    sanitize_mapping,
)


def test_sensitive_keys_are_redacted_recursively():
    sanitized = sanitize_mapping(
        {
            "service_type": "airtime",
            "idempotency_key": "caller-supplied",
            "nested": {"authorization": "Bearer abc", "amount": "5000"},
        }
    )

    assert sanitized["service_type"] == "airtime"
    assert sanitized["idempotency_key"] == REDACTED
    assert sanitized["nested"]["authorization"] == REDACTED
    assert sanitized["nested"]["amount"] == "5000"


def test_personal_data_is_masked_not_shown_whole():
    sanitized = sanitize_mapping({"beneficiary": "08030000001"})

    assert sanitized["beneficiary"] != "08030000001"
    assert sanitized["beneficiary"] == mask_personal("08030000001")


def test_mask_personal_keeps_shape_without_exposing_value():
    assert mask_personal("08030000001") == "080******01"
    assert mask_personal("12345") == "*****"


def test_non_json_values_are_coerced_for_display():
    identifier = UUID("11111111-1111-1111-1111-111111111111")
    sanitized = sanitize_mapping({"amount": Decimal("5000.00"), "id": identifier})

    assert sanitized["amount"] == "5000.00"
    assert sanitized["id"] == str(identifier)


def test_recorder_sequences_calls_and_extracts_transaction_id():
    recorder = MCPCallRecorder()

    first = recorder.record(
        tool="find_transaction_capabilities",
        arguments={"service_type": "airtime"},
        status="succeeded",
        result={"capabilities": []},
        duration_ms=1.5,
    )
    second = recorder.record(
        tool="execute_transaction",
        arguments={"beneficiary": "08030000001", "idempotency_key": "k"},
        status="succeeded",
        result={"transaction_id": "txn-1", "status": "success"},
        duration_ms=2.5,
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert [event.tool for event in recorder.events] == [
        "find_transaction_capabilities",
        "execute_transaction",
    ]
    assert second.transaction_id == "txn-1"
    assert second.arguments["idempotency_key"] == REDACTED
    assert second.arguments["beneficiary"] != "08030000001"


def test_recorder_marks_failures_with_error_detail():
    recorder = MCPCallRecorder()

    event = recorder.record(
        tool="execute_transaction",
        arguments={},
        status="failed",
        error="Transaction execution could not be completed",
    )

    assert event.status == "failed"
    assert event.result is None
    assert event.error == "Transaction execution could not be completed"


def test_attach_events_carries_real_events_on_the_error():
    recorder = MCPCallRecorder()
    recorder.record(tool="find_transaction_capabilities", arguments={}, status="succeeded")
    error = RuntimeError("boom")

    attach_events(error, recorder.events)

    assert error.mcp_events == recorder.events  # type: ignore[attr-defined]
