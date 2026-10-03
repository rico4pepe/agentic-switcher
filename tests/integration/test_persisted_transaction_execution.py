"""PostgreSQL integration tests for persisted transaction execution."""

from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from apps.api.app.database import SessionLocal, engine
from apps.api.app.domain.transaction import Transaction, TransactionState
from switcher.transactions.execution_service import TransactionExecutionService
from switcher.transactions.persistence_service import PersistedTransactionExecutionService
from vendors.base.adapter import VendorAdapter
from vendors.base.models import (
    AuthenticationRequest,
    AuthenticationResult,
    CustomerValidationRequest,
    CustomerValidationResult,
    TransactionExecutionRequest,
    TransactionQueryRequest,
    VendorCapabilities,
    VendorOperation,
    VendorTransactionResult,
    VendorTransactionStatus,
)
from vendors.vendor_a import VendorAAdapter


@pytest.fixture
def postgres_session() -> Iterator[Session]:
    """Provide a session connected only to the configured PostgreSQL database."""
    assert engine.dialect.name == "postgresql"
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def persisted_transaction_ids(postgres_session: Session) -> Iterator[list[UUID]]:
    """Remove just the records created by each integration test."""
    transaction_ids: list[UUID] = []
    try:
        yield transaction_ids
    finally:
        postgres_session.rollback()
        if transaction_ids:
            postgres_session.execute(
                delete(Transaction).where(Transaction.id.in_(transaction_ids))
            )
            postgres_session.commit()


def make_transaction(*, beneficiary: str = "08030000000") -> Transaction:
    """Build a canonical MTN airtime transaction."""
    return Transaction(
        product_type="airtime",
        network="MTN",
        beneficiary=beneficiary,
        amount=Decimal("5000.00"),
    )


def authenticated_vendor_a() -> VendorAAdapter:
    """Authenticate deterministic Vendor A for a successful workflow."""
    adapter = VendorAAdapter()
    adapter.authenticate(AuthenticationRequest({"api_key": "vendor_a_test_key"}))
    return adapter


class FailingExecutionAdapter(VendorAdapter):
    """Test adapter with successful validation and deterministic failure."""

    def authenticate(self, request: AuthenticationRequest) -> AuthenticationResult:
        return AuthenticationResult(authenticated=True)

    def get_capabilities(self) -> VendorCapabilities:
        return VendorCapabilities(
            vendor_code="failing_vendor",
            supported_operations=frozenset(VendorOperation),
        )

    def validate_customer(
        self, request: CustomerValidationRequest
    ) -> CustomerValidationResult:
        return CustomerValidationResult(is_valid=True)

    def execute_transaction(
        self, request: TransactionExecutionRequest
    ) -> VendorTransactionResult:
        return VendorTransactionResult(
            status=VendorTransactionStatus.FAILED,
            message="Vendor balance unavailable",
            raw_response={"code": "INSUFFICIENT_BALANCE"},
        )

    def query_transaction(
        self, request: TransactionQueryRequest
    ) -> VendorTransactionResult:
        return VendorTransactionResult(status=VendorTransactionStatus.UNKNOWN)


def execute_and_reload(
    session: Session,
    adapter: VendorAdapter,
    transaction: Transaction,
    transaction_ids: list[UUID],
) -> Transaction:
    """Execute, commit, then load a fresh ORM instance from PostgreSQL."""
    service = PersistedTransactionExecutionService(
        session,
        TransactionExecutionService(adapter),
    )
    persisted = service.execute(transaction)
    transaction_ids.append(persisted.id)
    transaction_id = persisted.id
    session.expunge_all()
    reloaded = session.get(Transaction, transaction_id)
    assert reloaded is not None
    return reloaded


def test_successful_vendor_a_transaction_persists_as_success(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    transaction = make_transaction()
    reloaded = execute_and_reload(
        postgres_session,
        authenticated_vendor_a(),
        transaction,
        persisted_transaction_ids,
    )

    assert reloaded.id == transaction.id
    assert reloaded.product_type == "airtime"
    assert reloaded.network == "MTN"
    assert reloaded.beneficiary == "08030000000"
    assert reloaded.amount == Decimal("5000.00")
    assert reloaded.state == TransactionState.SUCCESS
    assert reloaded.vendor_code == "vendor_a"
    assert reloaded.vendor_reference == f"vendor_a-{transaction.id}"
    assert reloaded.created_at is not None
    assert reloaded.updated_at is not None


def test_customer_validation_failure_persists_as_failed(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    reloaded = execute_and_reload(
        postgres_session,
        authenticated_vendor_a(),
        make_transaction(beneficiary="08039999999"),
        persisted_transaction_ids,
    )

    assert reloaded.state == TransactionState.FAILED
    assert reloaded.error_message == "Customer is not valid for Vendor A MTN airtime"
    assert reloaded.vendor_code == "vendor_a"


def test_execution_failure_persists_error_and_raw_response(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    reloaded = execute_and_reload(
        postgres_session,
        FailingExecutionAdapter(),
        make_transaction(),
        persisted_transaction_ids,
    )

    assert reloaded.state == TransactionState.FAILED
    assert reloaded.error_message == "Vendor balance unavailable"
    assert reloaded.raw_vendor_response == {"code": "INSUFFICIENT_BALANCE"}


def test_persisted_vendor_reference_matches_executed_transaction(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    transaction = make_transaction()
    reloaded = execute_and_reload(
        postgres_session,
        authenticated_vendor_a(),
        transaction,
        persisted_transaction_ids,
    )

    assert reloaded.vendor_reference == f"vendor_a-{transaction.id}"
