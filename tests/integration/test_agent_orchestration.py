"""Integration test for orchestration through the registered MCP tools."""

import asyncio
from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

from mcp.client import ClientSession
from mcp.client._memory import InMemoryTransport
from sqlalchemy import delete

from agent.llm_provider import StructuredOutput
from agent.orchestrator.service import (
    MCPClientBusinessTools,
    OrchestrationRequest,
    TransactionOrchestrator,
)
from agent.planner import ExecutionPlanPlanner
from apps.api.app.database import SessionLocal, engine
from apps.api.app.domain.transaction import Transaction
from apps.api.app.mcp_server.app import create_mcp_server
from vendors.vendor_a.operation_ledger import VendorAOperationRecord


class FixedPlanProvider:
    def generate_structured(
        self,
        _prompt: str,
        output_model: type[StructuredOutput],
    ) -> StructuredOutput:
        return output_model.model_validate(
            {
                "intent": "airtime_purchase",
                "service_type": "airtime",
                "product_type": "airtime",
                "network": "MTN",
                "beneficiary": "08030000000",
                "amount": "5000.00",
                "candidate_vendor": None,
                "steps": ["validate_customer", "execute_transaction"],
            }
        )


class RecordingMCPBusinessTools:
    def __init__(self, client: MCPClientBusinessTools) -> None:
        self._client = client
        self.calls: list[str] = []

    async def find_transaction_capabilities(
        self,
        *,
        service_type: str,
        product_type: str,
        network: str | None,
    ) -> Mapping[str, object]:
        self.calls.append("find_transaction_capabilities")
        return await self._client.find_transaction_capabilities(
            service_type=service_type,
            product_type=product_type,
            network=network,
        )

    async def execute_transaction(
        self,
        *,
        service_type: str,
        product_type: str,
        network: str | None,
        beneficiary: str,
        amount: Decimal,
        idempotency_key: str,
    ) -> Mapping[str, object]:
        self.calls.append("execute_transaction")
        return await self._client.execute_transaction(
            service_type=service_type,
            product_type=product_type,
            network=network,
            beneficiary=beneficiary,
            amount=amount,
            idempotency_key=idempotency_key,
        )


def test_orchestrator_discovers_plans_validates_and_executes_via_mcp():
    assert engine.dialect.name == "postgresql"
    transaction_id: UUID | None = None

    async def run_orchestration() -> tuple[Mapping[str, object], list[str]]:
        server, _ = create_mcp_server()
        async with InMemoryTransport(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                business_tools = RecordingMCPBusinessTools(
                    MCPClientBusinessTools(session)
                )
                orchestrator = TransactionOrchestrator(
                    ExecutionPlanPlanner(FixedPlanProvider()),
                    business_tools,
                )
                result = await orchestrator.execute(
                    OrchestrationRequest(
                        intent="airtime_purchase",
                        service_type="airtime",
                        product_type="airtime",
                        network="MTN",
                        beneficiary="08030000000",
                        amount=Decimal("5000.00"),
                    )
                )
                return result, business_tools.calls

    try:
        result, calls = asyncio.run(run_orchestration())
        transaction_id = UUID(str(result["transaction_id"]))

        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
            operation = session.get(VendorAOperationRecord, transaction_id)

        assert calls == ["find_transaction_capabilities", "execute_transaction"]
        assert result["status"] == "success"
        assert transaction is not None
        assert transaction.state.value == "success"
        assert operation is not None
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