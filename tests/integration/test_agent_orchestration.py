"""Integration test for orchestration through the registered MCP tools."""

import asyncio
from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

import pytest
from mcp.client import ClientSession
from mcp.client._memory import InMemoryTransport
from sqlalchemy import delete

from agent.llm_provider import StructuredOutput
from agent.orchestrator.service import (
    MCPClientBusinessTools,
    TransactionOrchestrator,
)
from agent.planner import ExecutionPlanPlanner
from agent.runtime.service import AgentRequest, AgentResult, AgentRuntime
from apps.api.app.database import SessionLocal, engine
from apps.api.app.config import settings
from switcher.transactions.execution_service import TransactionExecutionService
from switcher.vendor_adapter_resolver import create_authenticated_adapter
from apps.api.app.domain.transaction import Transaction
from apps.api.app.mcp_server.app import create_mcp_server
from policy.account_context import AccountContext, AccountType, DemoAccountContextProvider
from policy.engine import PolicyEngine
from switcher.routing import reset_vendor_availability, set_vendor_availability
from vendors.vendor_a.operation_ledger import VendorAOperationRecord
from vendors.vendor_a.operation_ledger import PostgresVendorAOperationLedger, VendorAOperationRecord
from vendors.vendor_b.operation_ledger import VendorBOperationRecord


class FixedPlanProvider:
    def __init__(self, candidate_vendor: str | None = None) -> None:
        self._candidate_vendor = candidate_vendor

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
                "beneficiary": "08030000001",
                "amount": "5000.00",
                "candidate_vendor": self._candidate_vendor,
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
        vendor_code: str,
        idempotency_key: str,
    ) -> Mapping[str, object]:
        self.calls.append("execute_transaction")
        return await self._client.execute_transaction(
            service_type=service_type,
            product_type=product_type,
            network=network,
            beneficiary=beneficiary,
            amount=amount,
            vendor_code=vendor_code,
            idempotency_key=idempotency_key,
        )


class StaticCapabilityBusinessTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def find_transaction_capabilities(
        self,
        *,
        service_type: str,
        product_type: str,
        network: str | None,
    ) -> Mapping[str, object]:
        self.calls.append("find_transaction_capabilities")
        return {
            "capabilities": [
                {
                    "vendor_code": "vendor_a",
                    "service_type": service_type,
                    "product_type": product_type,
                    "network": network,
                    "supported_operations": [
                        "validate_customer",
                        "execute_transaction",
                    ],
                    "workflow": [
                        {"operation": "validate_customer", "required": True},
                        {"operation": "execute_transaction", "required": True},
                    ],
                    "product_attributes": {},
                }
            ]
        }

    async def execute_transaction(self, **_kwargs) -> Mapping[str, object]:
        self.calls.append("execute_transaction")
        raise AssertionError("Policy-denied request reached MCP execution")


def test_agent_runtime_executes_transaction_through_orchestrator_and_mcp():
    assert engine.dialect.name == "postgresql"
    transaction_id: UUID | None = None

    async def run_orchestration() -> tuple[AgentResult, list[str]]:
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
                result = await runtime.execute(
                    AgentRequest(
                        intent="airtime_purchase",
                        service_type="airtime",
                        product_type="airtime",
                        network="MTN",
                        beneficiary="08030000001",
                        amount=Decimal("5000.00"),
                    )
                )
                return result, business_tools.calls

    try:
        result, calls = asyncio.run(run_orchestration())
        transaction_id = result.transaction_id
        assert transaction_id is not None

        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
            operation = session.get(VendorAOperationRecord, transaction_id)

        assert calls == ["find_transaction_capabilities", "execute_transaction"]
        assert result.status == "success"
        assert result.action == "allow"
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


def test_orchestrator_candidate_vendor_unavailable_executes_with_vendor_b():
    assert engine.dialect.name == "postgresql"
    transaction_id: UUID | None = None

    async def run_orchestration() -> AgentResult:
        server, _ = create_mcp_server()
        async with InMemoryTransport(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                runtime = AgentRuntime(
                    TransactionOrchestrator(
                        ExecutionPlanPlanner(FixedPlanProvider(candidate_vendor="vendor_a")),
                        MCPClientBusinessTools(session),
                    )
                )
                return await runtime.execute(
                    AgentRequest(
                        intent="airtime_purchase",
                        service_type="airtime",
                        product_type="airtime",
                        network="MTN",
                        beneficiary="08030000001",
                        amount=Decimal("5000.00"),
                    )
                )

    set_vendor_availability("vendor_a", False)
    try:
        result = asyncio.run(run_orchestration())
        transaction_id = result.transaction_id
        assert transaction_id is not None

        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
            operation = session.get(VendorBOperationRecord, transaction_id)

        assert result.status == "success"
        assert result.action == "allow"
        assert result.vendor_code == "vendor_b"
        assert transaction is not None
        assert transaction.vendor_code == "vendor_b"
        assert transaction.state.value == "success"
        assert operation is not None
        assert operation.status == "success"
    finally:
        reset_vendor_availability()
        if transaction_id is not None:
            with SessionLocal() as session:
                session.execute(
                    delete(VendorBOperationRecord).where(
                        VendorBOperationRecord.transaction_id == transaction_id
                    )
                )
                session.execute(
                    delete(Transaction).where(Transaction.id == transaction_id)
                )
                session.commit()


def test_policy_denial_stops_agent_before_mcp_or_vendor_submission(
    monkeypatch: pytest.MonkeyPatch,
):
    account_contexts = DemoAccountContextProvider(
        (
            AccountContext(
                beneficiary="08030000001",
                account_type=AccountType.PREPAID,
                balance=Decimal("2000.00"),
            ),
        )
    )
    policy_engine = PolicyEngine(account_contexts)

    async def run_orchestration() -> tuple[AgentResult, list[str]]:
        business_tools = StaticCapabilityBusinessTools()
        runtime = AgentRuntime(
            TransactionOrchestrator(
                ExecutionPlanPlanner(FixedPlanProvider(candidate_vendor="vendor_a")),
                business_tools,
                policy_engine=policy_engine,
            )
        )
        result = await runtime.execute(
            AgentRequest(
                intent="airtime_purchase",
                service_type="airtime",
                product_type="airtime",
                network="MTN",
                beneficiary="08030000001",
                amount=Decimal("5000.00"),
            )
        )
        return result, business_tools.calls

    submissions: list[str] = []

    def record_submission(*_args, **_kwargs):
        submissions.append("submitted")

    monkeypatch.setattr(
        "vendors.vendor_a.operation_ledger.PostgresVendorAOperationLedger.submit",
        record_submission,
    )
    monkeypatch.setattr(
        "vendors.vendor_b.operation_ledger.PostgresVendorBOperationLedger.submit",
        record_submission,
    )

    result, calls = asyncio.run(run_orchestration())

    assert result.status == "denied"
    assert result.action == "deny"
    assert result.reason == "Insufficient balance"
    assert result.transaction_id is None
    assert result.vendor_code is None
    assert result.vendor_reference is None
    assert calls == ["find_transaction_capabilities"]
    assert submissions == []

def test_vendor_a_unavailable_scenario_selects_vendor_b_execution_level():
    assert engine.dialect.name == "postgresql"
    transaction_id: UUID | None = None

    from switcher.demo.scenarios import DemoScenarioName, set_demo_scenario, reset_demo_scenario

    async def run_orchestration() -> AgentResult:
        server, _ = create_mcp_server()
        async with InMemoryTransport(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                runtime = AgentRuntime(
                    TransactionOrchestrator(
                        ExecutionPlanPlanner(FixedPlanProvider(candidate_vendor="vendor_a")),
                        MCPClientBusinessTools(session),
                    )
                )
                return await runtime.execute(
                    AgentRequest(
                        intent="airtime_purchase",
                        service_type="airtime",
                        product_type="airtime",
                        network="MTN",
                        beneficiary="08030000001",
                        amount=Decimal("5000.00"),
                    )
                )

    set_demo_scenario(DemoScenarioName.VENDOR_A_UNAVAILABLE)
    try:
        result = asyncio.run(run_orchestration())
        transaction_id = result.transaction_id
        assert transaction_id is not None

        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
            operation = session.get(VendorBOperationRecord, transaction_id)

        assert result.status == "success"
        assert result.action == "allow"
        assert result.vendor_code == "vendor_b"
        assert result.planner_candidate_vendor == "vendor_a"
        assert transaction is not None
        assert transaction.vendor_code == "vendor_b"
        assert transaction.state.value == "success"
        assert operation is not None
    finally:
        reset_demo_scenario()
        if transaction_id is not None:
            with SessionLocal() as session:
                session.execute(
                    delete(VendorBOperationRecord).where(
                        VendorBOperationRecord.transaction_id == transaction_id
                    )
                )
                session.execute(
                    delete(Transaction).where(Transaction.id == transaction_id)
                )
                session.commit()


def test_policy_denied_scenario_denies_without_vendor_submission(monkeypatch: pytest.MonkeyPatch):
    from switcher.demo.scenarios import DemoScenarioName, set_demo_scenario, reset_demo_scenario

    account_contexts = DemoAccountContextProvider(
        (
            AccountContext(
                beneficiary="08030000001",
                account_type=AccountType.PREPAID,
                balance=Decimal("2000.00"),
            ),
        )
    )
    policy_engine = PolicyEngine(account_contexts)

    async def run_orchestration() -> tuple[AgentResult, list[str]]:
        business_tools = StaticCapabilityBusinessTools()
        runtime = AgentRuntime(
            TransactionOrchestrator(
                ExecutionPlanPlanner(FixedPlanProvider(candidate_vendor="vendor_a")),
                business_tools,
                policy_engine=policy_engine,
            )
        )
        result = await runtime.execute(
            AgentRequest(
                intent="airtime_purchase",
                service_type="airtime",
                product_type="airtime",
                network="MTN",
                beneficiary="08030000001",
                amount=Decimal("5000.00"),
            )
        )
        return result, business_tools.calls

    submissions: list[str] = []

    def record_submission(*_args, **_kwargs):
        submissions.append("submitted")

    monkeypatch.setattr(
        "vendors.vendor_a.operation_ledger.PostgresVendorAOperationLedger.submit",
        record_submission,
    )
    monkeypatch.setattr(
        "vendors.vendor_b.operation_ledger.PostgresVendorBOperationLedger.submit",
        record_submission,
    )

    set_demo_scenario(DemoScenarioName.POLICY_DENIED)
    try:
        result, calls = asyncio.run(run_orchestration())
        assert result.status == "denied"
        assert result.action == "deny"
        assert result.transaction_id is None
        assert result.vendor_code is None
        assert calls == ["find_transaction_capabilities"]
        assert submissions == []
    finally:
        reset_demo_scenario()



def test_timeout_scenario_produces_persisted_unknown_and_investigation_uses_query_path():
    assert engine.dialect.name == "postgresql"
    transaction_id: UUID | None = None

    from switcher.demo.scenarios import DemoScenarioName, set_demo_scenario, reset_demo_scenario
    from switcher.transactions.investigator import TransactionInvestigator

    async def run_orchestration() -> AgentResult:
        server, _ = create_mcp_server()
        async with InMemoryTransport(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                runtime = AgentRuntime(
                    TransactionOrchestrator(
                        ExecutionPlanPlanner(FixedPlanProvider(candidate_vendor="vendor_a")),
                        MCPClientBusinessTools(session),
                    )
                )
                return await runtime.execute(
                    AgentRequest(
                        intent="airtime_purchase",
                        service_type="airtime",
                        product_type="airtime",
                        network="MTN",
                        beneficiary="08030000001",
                        amount=Decimal("5000.00"),
                    )
                )

    set_demo_scenario(DemoScenarioName.TIMEOUT)
    try:
        result = asyncio.run(run_orchestration())
        transaction_id = result.transaction_id
        assert transaction_id is not None

        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)

        assert transaction is not None
        assert transaction.state.value == "unknown"

        # Investigate using existing query path
        with SessionLocal() as session:
            investigator = TransactionInvestigator(
                session,
                lambda: TransactionExecutionService(
                    create_authenticated_adapter("vendor_a", settings)
                ),
            )
            investigated = investigator.investigate(transaction_id)
            assert investigated is not None
    finally:
        reset_demo_scenario()
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

def test_normal_scenario_restores_and_executes_successfully():
    assert engine.dialect.name == "postgresql"
    transaction_id: UUID | None = None

    from switcher.demo.scenarios import DemoScenarioName, set_demo_scenario, reset_demo_scenario
    from switcher.routing import reset_vendor_availability, set_vendor_availability
    from policy.account_context import AccountContext, AccountType, DemoAccountContextProvider
    from policy.engine import PolicyEngine

    async def run_orchestration(policy_engine=None) -> AgentResult:
        server, _ = create_mcp_server()
        async with InMemoryTransport(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                runtime = AgentRuntime(
                    TransactionOrchestrator(
                        ExecutionPlanPlanner(FixedPlanProvider(candidate_vendor="vendor_a")),
                        MCPClientBusinessTools(session),
                        policy_engine=policy_engine or default_policy_engine,
                    )
                )
                return await runtime.execute(
                    AgentRequest(
                        intent="airtime_purchase",
                        service_type="airtime",
                        product_type="airtime",
                        network="MTN",
                        beneficiary="08030000001",
                        amount=Decimal("5000.00"),
                    )
                )

    try:
        # Set non-normal conditions and then restore to normal
        set_demo_scenario(DemoScenarioName.VENDOR_A_UNAVAILABLE)
        set_vendor_availability("vendor_a", False)
        reset_demo_scenario()
        reset_vendor_availability()

        # Normal account context with sufficient balance
        account_contexts = DemoAccountContextProvider(
            (
                AccountContext(
                    beneficiary="08030000001",
                    account_type=AccountType.PREPAID,
                    balance=Decimal("10000.00"),
                ),
            )
        )
        policy_engine = PolicyEngine(account_contexts)

        result = asyncio.run(run_orchestration(policy_engine=policy_engine))
        transaction_id = result.transaction_id
        assert transaction_id is not None
        assert result.status == "success"
        assert result.action == "allow"
        assert result.vendor_code == "vendor_a"

        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
            operation = session.get(VendorAOperationRecord, transaction_id)

        assert transaction is not None
        assert transaction.state.value == "success"
        assert operation is not None
    finally:
        reset_demo_scenario()
        reset_vendor_availability()
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


def test_planner_a_a_unavailable_scenario_candidate_a_but_switcher_selects_b():
    assert engine.dialect.name == "postgresql"
    transaction_id: UUID | None = None

    from switcher.demo.scenarios import DemoScenarioName, set_demo_scenario, reset_demo_scenario

    async def run_orchestration() -> AgentResult:
        server, _ = create_mcp_server()
        async with InMemoryTransport(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                runtime = AgentRuntime(
                    TransactionOrchestrator(
                        ExecutionPlanPlanner(FixedPlanProvider(candidate_vendor="vendor_a")),
                        MCPClientBusinessTools(session),
                    )
                )
                return await runtime.execute(
                    AgentRequest(
                        intent="airtime_purchase",
                        service_type="airtime",
                        product_type="airtime",
                        network="MTN",
                        beneficiary="08030000001",
                        amount=Decimal("5000.00"),
                    )
                )

    set_demo_scenario(DemoScenarioName.PLANNER_A_A_UNAVAILABLE)
    try:
        result = asyncio.run(run_orchestration())
        transaction_id = result.transaction_id
        assert transaction_id is not None
        assert result.planner_candidate_vendor == "vendor_a"
        assert result.vendor_code == "vendor_b"
        assert result.status == "success"

        with SessionLocal() as session:
            transaction = session.get(Transaction, transaction_id)
            operation = session.get(VendorBOperationRecord, transaction_id)

        assert transaction.vendor_code == "vendor_b"
        assert operation is not None
    finally:
        reset_demo_scenario()
        if transaction_id is not None:
            with SessionLocal() as session:
                session.execute(
                    delete(VendorBOperationRecord).where(
                        VendorBOperationRecord.transaction_id == transaction_id
                    )
                )
                session.execute(
                    delete(Transaction).where(Transaction.id == transaction_id)
                )
                session.commit()
