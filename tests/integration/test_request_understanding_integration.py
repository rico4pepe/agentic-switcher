"""Integration: natural language through the full agent path to an explanation.

One focused test for the 4I-L boundary:

    Natural Language
        -> RequestUnderstanding
        -> AgentRequest
        -> AgentRuntime
        -> TransactionOrchestrator
        -> Policy
        -> Switcher
        -> MCP business execution
        -> Vendor
        -> AgentResult
        -> TransactionExplainer

It reuses the existing integration infrastructure (in-memory MCP transport,
fixed planner, simulated vendors, Postgres transaction records) and adds no
second execution architecture.
"""

import asyncio
from decimal import Decimal
from uuid import UUID

from mcp.client import ClientSession
from mcp.client._memory import InMemoryTransport
from sqlalchemy import delete

from agent.explainer import TransactionExplainer
from agent.orchestrator.service import (
    MCPClientBusinessTools,
    TransactionOrchestrator,
)
from agent.planner import ExecutionPlanPlanner
from agent.request_understanding import RequestUnderstanding
from agent.runtime.service import AgentRequest, AgentResult, AgentRuntime
from apps.api.app.database import SessionLocal, engine
from apps.api.app.domain.transaction import Transaction
from apps.api.app.mcp_server.app import create_mcp_server
from tests.integration.test_agent_orchestration import (
    FixedPlanProvider,
    RecordingMCPBusinessTools,
)
from vendors.vendor_a.operation_ledger import VendorAOperationRecord


def test_natural_language_request_flows_to_explained_success() -> None:
    assert engine.dialect.name == "postgresql"
    transaction_id: UUID | None = None

    natural_language = "Buy ₦5,000 MTN airtime for 08030000001."

    request = RequestUnderstanding().parse(natural_language)
    assert request == AgentRequest(
        intent="airtime_purchase",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        beneficiary="08030000001",
        amount=Decimal("5000.00"),
    )

    async def run_path() -> tuple[AgentResult, list[str]]:
        server, _ = create_mcp_server()
        async with InMemoryTransport(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                business_tools = RecordingMCPBusinessTools(
                    MCPClientBusinessTools(session)
                )
                runtime = AgentRuntime(
                    TransactionOrchestrator(
                        ExecutionPlanPlanner(FixedPlanProvider()),
                        business_tools,
                    )
                )
                result = await runtime.execute(request)
                return result, business_tools.calls

    try:
        result, calls = asyncio.run(run_path())
        transaction_id = result.transaction_id
        assert transaction_id is not None

        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
            operation = session.get(VendorAOperationRecord, transaction_id)

        # Policy allowed, Switcher chose Vendor A, MCP execution reached it.
        assert calls == ["find_transaction_capabilities", "execute_transaction"]
        assert result.status == "success"
        assert result.action == "allow"
        assert result.vendor_code == "vendor_a"
        assert transaction is not None
        assert transaction.state.value == "success"
        assert operation is not None

        explanation = TransactionExplainer().explain(result)
        assert "₦5,000 MTN airtime purchase for 08030000001" in explanation
        assert "completed successfully" in explanation
        assert "Vendor A" in explanation
    finally:
        if transaction_id is not None:
            with SessionLocal() as session:
                session.execute(
                    delete(VendorAOperationRecord).where(
                        VendorAOperationRecord.transaction_id == transaction_id
                    )
                )
                session.execute(
                    delete(Transaction).where(Transaction.id == transaction_id)
                )
                session.commit()
