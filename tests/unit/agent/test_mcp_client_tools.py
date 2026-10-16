"""Tests for MCP client instrumentation at the tool-call boundary.

Only a real ``tools/call`` appends an event, and recording is observation only:
it must not change what is called, what is returned, or which error is raised.
"""

import asyncio
from decimal import Decimal

import pytest

from agent.orchestrator.mcp_events import MCPCallRecorder, mask_personal
from agent.orchestrator.service import MCPBusinessToolError, MCPClientBusinessTools


class FakeContent:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeResult:
    def __init__(
        self,
        *,
        structured_content: object = None,
        is_error: bool = False,
        content: list[object] | None = None,
    ) -> None:
        self.structured_content = structured_content
        self.is_error = is_error
        self.content = content or []


class FakeSession:
    def __init__(self, *, result: object = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        self.calls.append((name, arguments))
        if self._error is not None:
            raise self._error
        return self._result


def test_discovery_success_is_recorded_with_sanitized_arguments():
    session = FakeSession(result=FakeResult(structured_content={"capabilities": []}))
    recorder = MCPCallRecorder()
    tools = MCPClientBusinessTools(session, recorder=recorder)

    content = asyncio.run(
        tools.find_transaction_capabilities(
            service_type="airtime",
            product_type="airtime",
            network="MTN",
        )
    )

    assert content == {"capabilities": []}
    assert session.calls == [
        (
            "find_transaction_capabilities",
            {"service_type": "airtime", "product_type": "airtime", "network": "MTN"},
        )
    ]
    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event.tool == "find_transaction_capabilities"
    assert event.status == "succeeded"
    assert event.duration_ms is not None
    assert event.duration_ms >= 0


def test_execution_success_records_transaction_and_redacts_key():
    session = FakeSession(
        result=FakeResult(
            structured_content={
                "transaction_id": "txn-1",
                "status": "success",
                "beneficiary": "08030000001",
            }
        )
    )
    recorder = MCPCallRecorder()
    tools = MCPClientBusinessTools(session, recorder=recorder)

    asyncio.run(
        tools.execute_transaction(
            service_type="airtime",
            product_type="airtime",
            network="MTN",
            beneficiary="08030000001",
            amount=Decimal("5000"),
            vendor_code="vendor_a",
            idempotency_key="caller-supplied",
        )
    )

    event = recorder.events[0]
    assert event.tool == "execute_transaction"
    assert event.status == "succeeded"
    assert event.transaction_id == "txn-1"
    assert event.arguments["idempotency_key"] == "[redacted]"
    assert event.arguments["beneficiary"] == mask_personal("08030000001")
    assert event.arguments["vendor_code"] == "vendor_a"
    assert event.result is not None
    assert event.result["beneficiary"] == mask_personal("08030000001")


def test_omitted_vendor_code_is_not_injected_into_the_recorded_call():
    session = FakeSession(result=FakeResult(structured_content={"status": "unknown"}))
    recorder = MCPCallRecorder()
    tools = MCPClientBusinessTools(session, recorder=recorder)

    asyncio.run(
        tools.execute_transaction(
            service_type="airtime",
            product_type="airtime",
            network=None,
            beneficiary="08030000001",
            amount=Decimal("5000"),
            vendor_code="",
            idempotency_key="k",
        )
    )

    name, arguments = session.calls[0]
    assert name == "execute_transaction"
    assert "vendor_code" not in arguments
    assert "vendor_code" not in recorder.events[0].arguments


def test_tool_error_result_is_recorded_as_failure_and_still_raises():
    session = FakeSession(
        result=FakeResult(is_error=True, content=[FakeContent("vendor unavailable")])
    )
    recorder = MCPCallRecorder()
    tools = MCPClientBusinessTools(session, recorder=recorder)

    with pytest.raises(MCPBusinessToolError) as error:
        asyncio.run(
            tools.execute_transaction(
                service_type="airtime",
                product_type="airtime",
                network="MTN",
                beneficiary="08030000001",
                amount=Decimal("5000"),
                vendor_code="vendor_a",
                idempotency_key="k",
            )
        )

    assert str(error.value) == "MCP tool execute_transaction returned an error"
    event = recorder.events[0]
    assert event.status == "failed"
    assert event.error == "vendor unavailable"
    assert event.result is None


def test_missing_structured_content_is_recorded_as_failure():
    session = FakeSession(result=FakeResult(structured_content=None))
    recorder = MCPCallRecorder()
    tools = MCPClientBusinessTools(session, recorder=recorder)

    with pytest.raises(MCPBusinessToolError) as error:
        asyncio.run(
            tools.find_transaction_capabilities(
                service_type="airtime",
                product_type="airtime",
                network=None,
            )
        )

    assert (
        str(error.value)
        == "MCP tool find_transaction_capabilities returned no structured content"
    )
    assert recorder.events[0].status == "failed"


def test_transport_exception_is_recorded_as_failure_and_reraised():
    session = FakeSession(error=RuntimeError("network down"))
    recorder = MCPCallRecorder()
    tools = MCPClientBusinessTools(session, recorder=recorder)

    with pytest.raises(RuntimeError, match="network down"):
        asyncio.run(
            tools.find_transaction_capabilities(
                service_type="airtime",
                product_type="airtime",
                network=None,
            )
        )

    event = recorder.events[0]
    assert event.status == "failed"
    assert event.error == "network down"


def test_without_a_recorder_behavior_is_unchanged():
    session = FakeSession(result=FakeResult(structured_content={"capabilities": []}))
    tools = MCPClientBusinessTools(session)

    content = asyncio.run(
        tools.find_transaction_capabilities(
            service_type="airtime",
            product_type="airtime",
            network=None,
        )
    )

    assert content == {"capabilities": []}
