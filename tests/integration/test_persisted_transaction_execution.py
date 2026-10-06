"""PostgreSQL integration tests for persisted transaction execution."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Event, Lock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.database import SessionLocal, engine
from apps.api.app.domain.transaction import Transaction, TransactionState
from switcher.transactions.execution_service import TransactionExecutionService
from switcher.transactions.persistence_service import (
    IdempotencyConflictError,
    PersistedTransactionExecutionService,
)
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
from vendors.vendor_a.operation_ledger import (
    PostgresVendorAOperationLedger,
    VendorAOperationRecord,
)


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
                delete(VendorAOperationRecord).where(
                    VendorAOperationRecord.transaction_id.in_(transaction_ids)
                )
            )
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
    adapter = VendorAAdapter(PostgresVendorAOperationLedger(SessionLocal))
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


class CountingExecutionAdapter(FailingExecutionAdapter):
    """Count side-effecting submissions while keeping deterministic results."""

    def __init__(self) -> None:
        self.execution_count = 0
        self.query_count = 0

    def execute_transaction(
        self, request: TransactionExecutionRequest
    ) -> VendorTransactionResult:
        self.execution_count += 1
        return VendorTransactionResult(
            status=VendorTransactionStatus.SUCCESS,
            vendor_reference=f"counted-{request.transaction_id}",
        )

    def query_transaction(
        self, request: TransactionQueryRequest
    ) -> VendorTransactionResult:
        self.query_count += 1
        return VendorTransactionResult(status=VendorTransactionStatus.UNKNOWN)


def execute_with_key(
    session: Session,
    adapter: VendorAdapter,
    key: str,
    *,
    beneficiary: str = "08030000000",
) -> Transaction:
    transaction = make_transaction(beneficiary=beneficiary)
    transaction.idempotency_key = key
    return PersistedTransactionExecutionService(
        session,
        TransactionExecutionService(adapter),
    ).execute(transaction)


def test_validating_transaction_resumes_and_submits_once(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    transaction = make_transaction()
    transaction.idempotency_key = f"resume-validating-{uuid4()}"
    transaction.state = TransactionState.VALIDATING
    postgres_session.add(transaction)
    postgres_session.commit()
    persisted_transaction_ids.append(transaction.id)
    adapter = CountingExecutionAdapter()

    resumed = execute_with_key(
        postgres_session,
        adapter,
        transaction.idempotency_key or "",
    )

    assert resumed.id == transaction.id
    assert resumed.state == TransactionState.SUCCESS
    assert adapter.execution_count == 1


def test_invalid_validation_resume_resolves_failed_without_submission(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    transaction = make_transaction(beneficiary="08039999999")
    transaction.idempotency_key = f"resume-invalid-{uuid4()}"
    transaction.state = TransactionState.VALIDATING
    postgres_session.add(transaction)
    postgres_session.commit()
    persisted_transaction_ids.append(transaction.id)

    class InvalidValidationAdapter(CountingExecutionAdapter):
        def validate_customer(
            self, request: CustomerValidationRequest
        ) -> CustomerValidationResult:
            return CustomerValidationResult(
                is_valid=False,
                message="Customer is not valid for Vendor A MTN airtime",
            )

    adapter = InvalidValidationAdapter()

    resumed = execute_with_key(
        postgres_session,
        adapter,
        transaction.idempotency_key or "",
        beneficiary="08039999999",
    )

    assert resumed.id == transaction.id
    assert resumed.state == TransactionState.FAILED
    assert resumed.error_message == "Customer is not valid for Vendor A MTN airtime"
    assert adapter.execution_count == 0


def test_same_idempotency_key_and_inputs_reuse_transaction_without_resubmission(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    adapter = CountingExecutionAdapter()
    key = f"same-inputs-{uuid4()}"

    first = execute_with_key(postgres_session, adapter, key)
    persisted_transaction_ids.append(first.id)
    second = execute_with_key(postgres_session, adapter, key)

    assert second.id == first.id
    assert second.state == TransactionState.SUCCESS
    assert adapter.execution_count == 1


def test_idempotency_key_conflict_is_rejected_before_vendor_execution(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    adapter = CountingExecutionAdapter()
    key = f"conflict-{uuid4()}"
    first = execute_with_key(postgres_session, adapter, key)
    persisted_transaction_ids.append(first.id)

    with pytest.raises(IdempotencyConflictError):
        execute_with_key(
            postgres_session,
            adapter,
            key,
            beneficiary="08031112222",
        )

    assert adapter.execution_count == 1


def test_different_idempotency_keys_create_independent_transactions(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    adapter = CountingExecutionAdapter()
    first = execute_with_key(postgres_session, adapter, f"first-{uuid4()}")
    second = execute_with_key(postgres_session, adapter, f"second-{uuid4()}")
    persisted_transaction_ids.extend([first.id, second.id])

    assert first.id != second.id
    assert adapter.execution_count == 2


def test_transaction_identity_and_key_are_persisted_before_vendor_submission(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    class IdentityCheckingAdapter(CountingExecutionAdapter):
        def execute_transaction(
            self, request: TransactionExecutionRequest
        ) -> VendorTransactionResult:
            persisted = postgres_session.get(Transaction, request.transaction_id)
            assert persisted is not None
            assert persisted.idempotency_key == key
            assert persisted.state == TransactionState.SUBMITTING
            return super().execute_transaction(request)

    key = f"identity-before-submit-{uuid4()}"
    adapter = IdentityCheckingAdapter()
    result = execute_with_key(postgres_session, adapter, key)
    persisted_transaction_ids.append(result.id)

    assert result.state == TransactionState.SUCCESS


def test_concurrent_validating_recovery_cannot_overwrite_state_or_submit_twice(
    persisted_transaction_ids: list[UUID],
):
    key = f"concurrent-{uuid4()}"
    seed_session = SessionLocal()
    canonical = make_transaction()
    canonical.idempotency_key = key
    canonical.state = TransactionState.VALIDATING
    seed_session.add(canonical)
    seed_session.commit()
    transaction_id = canonical.id
    persisted_transaction_ids.append(transaction_id)
    seed_session.close()

    both_validations_started = Barrier(2)
    submission_completed = Event()
    validation_lock = Lock()
    validation_call_count = 0
    submission_count = 0
    submission_lock = Lock()

    class BlockingExecutionAdapter(VendorAdapter):
        def authenticate(
            self, request: AuthenticationRequest
        ) -> AuthenticationResult:
            return AuthenticationResult(authenticated=True)

        def get_capabilities(self) -> VendorCapabilities:
            return VendorCapabilities(
                vendor_code="concurrency-test",
                supported_operations=frozenset(VendorOperation),
            )

        def validate_customer(
            self, request: CustomerValidationRequest
        ) -> CustomerValidationResult:
            nonlocal validation_call_count
            with validation_lock:
                validation_call_count += 1
                call_number = validation_call_count
            both_validations_started.wait(timeout=10)
            if call_number == 2:
                assert submission_completed.wait(timeout=10)
            return CustomerValidationResult(is_valid=True)

        def execute_transaction(
            self, request: TransactionExecutionRequest
        ) -> VendorTransactionResult:
            nonlocal submission_count
            with submission_lock:
                submission_count += 1
            submission_completed.set()
            return VendorTransactionResult(
                status=VendorTransactionStatus.SUCCESS,
                vendor_reference=f"concurrency-{request.transaction_id}",
            )

        def query_transaction(
            self, request: TransactionQueryRequest
        ) -> VendorTransactionResult:
            return VendorTransactionResult(status=VendorTransactionStatus.UNKNOWN)

    adapter = BlockingExecutionAdapter()

    def invoke() -> Transaction:
        session = SessionLocal()
        try:
            requested = make_transaction()
            requested.idempotency_key = key
            return PersistedTransactionExecutionService(
                session,
                TransactionExecutionService(adapter),
            ).execute(requested)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(invoke)
        second_future = executor.submit(invoke)
        first_result = first_future.result(timeout=10)
        second_result = second_future.result(timeout=10)

    assert first_result.state == TransactionState.SUCCESS
    assert second_result.state == TransactionState.SUCCESS
    assert first_result.id == transaction_id
    assert second_result.id == transaction_id
    assert validation_call_count == 2
    assert submission_count == 1

    verify_session = SessionLocal()
    try:
        persisted = verify_session.get(Transaction, transaction_id)
        assert persisted is not None
        assert persisted.state == TransactionState.SUCCESS
    finally:
        verify_session.close()


def test_idempotency_key_is_unique_in_database(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    key = f"db-unique-{uuid4()}"
    first = make_transaction()
    first.idempotency_key = key
    second = make_transaction()
    second.idempotency_key = key
    postgres_session.add(first)
    postgres_session.commit()
    persisted_transaction_ids.append(first.id)
    postgres_session.add(second)

    with pytest.raises(IntegrityError):
        postgres_session.commit()

    postgres_session.rollback()
    assert postgres_session.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.idempotency_key == key)
    ) == 1


@pytest.mark.parametrize(
    ("status", "expected_state"),
    [
        (VendorTransactionStatus.SUCCESS, TransactionState.SUCCESS),
        (VendorTransactionStatus.FAILED, TransactionState.FAILED),
        (VendorTransactionStatus.PENDING, TransactionState.UNKNOWN),
    ],
)
def test_vendor_operation_ledger_survives_adapter_recreation(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
    status: VendorTransactionStatus,
    expected_state: TransactionState,
):
    transaction = make_transaction()
    transaction.idempotency_key = f"vendor-ledger-{uuid4()}"
    postgres_session.add(transaction)
    postgres_session.commit()
    persisted_transaction_ids.append(transaction.id)

    ledger = PostgresVendorAOperationLedger(
        SessionLocal,
        submission_status=status,
    )
    adapter = VendorAAdapter(ledger)
    adapter.authenticate(AuthenticationRequest({"api_key": "vendor_a_test_key"}))
    adapter.validate_customer(
        CustomerValidationRequest(
            product_type="airtime",
            network="MTN",
            beneficiary=transaction.beneficiary or "",
        )
    )
    request = TransactionExecutionRequest(
        transaction_id=transaction.id,
        product_type=transaction.product_type,
        network=transaction.network,
        beneficiary=transaction.beneficiary or "",
        amount=transaction.amount,
    )
    submitted = adapter.execute_transaction(request)
    recreated_adapter = VendorAAdapter(PostgresVendorAOperationLedger(SessionLocal))
    queried = recreated_adapter.query_transaction(
        TransactionQueryRequest(transaction_id=transaction.id)
    )

    assert submitted.status == status
    assert queried.status == status
    assert (
        TransactionState.SUCCESS
        if queried.status == VendorTransactionStatus.SUCCESS
        else TransactionState.FAILED
        if queried.status == VendorTransactionStatus.FAILED
        else TransactionState.UNKNOWN
    ) == expected_state


@pytest.mark.parametrize(
    ("vendor_status", "expected_state"),
    [
        (VendorTransactionStatus.SUCCESS, TransactionState.SUCCESS),
        (VendorTransactionStatus.FAILED, TransactionState.FAILED),
        (VendorTransactionStatus.PENDING, TransactionState.UNKNOWN),
    ],
)
def test_repeated_uncertain_operation_requeries_without_vendor_submission(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
    vendor_status: VendorTransactionStatus,
    expected_state: TransactionState,
):
    transaction = make_transaction()
    transaction.idempotency_key = f"recover-{uuid4()}"
    transaction.id = uuid4()
    transaction.state = TransactionState.SUBMITTING
    postgres_session.add(transaction)
    postgres_session.commit()
    persisted_transaction_ids.append(transaction.id)

    durable_ledger = PostgresVendorAOperationLedger(
        SessionLocal,
        submission_status=vendor_status,
    )
    durable_ledger.submit(
        TransactionExecutionRequest(
            transaction_id=transaction.id,
            product_type=transaction.product_type,
            network=transaction.network,
            beneficiary=transaction.beneficiary or "",
            amount=transaction.amount,
        )
    )

    class CountingLedger:
        def __init__(self) -> None:
            self.submit_count = 0
            self.query_count = 0

        def submit(self, request: TransactionExecutionRequest) -> VendorTransactionResult:
            self.submit_count += 1
            return durable_ledger.submit(request)

        def query(self, transaction_id: UUID) -> VendorTransactionResult:
            self.query_count += 1
            return durable_ledger.query(transaction_id)

    counting_ledger = CountingLedger()
    adapter = VendorAAdapter(counting_ledger)
    adapter.authenticate(AuthenticationRequest({"api_key": "vendor_a_test_key"}))
    service = PersistedTransactionExecutionService(
        postgres_session,
        TransactionExecutionService(adapter),
    )

    recovered = service.execute(
        make_transaction_with_key(
            transaction.idempotency_key or "",
            beneficiary=transaction.beneficiary or "",
        )
    )

    assert recovered.id == transaction.id
    assert recovered.state == expected_state
    assert counting_ledger.submit_count == 0
    assert counting_ledger.query_count == 1
    assert postgres_session.get(VendorAOperationRecord, transaction.id) is not None


@pytest.mark.parametrize(
    ("vendor_status", "expected_state"),
    [
        (VendorTransactionStatus.SUCCESS, TransactionState.SUCCESS),
        (VendorTransactionStatus.FAILED, TransactionState.FAILED),
    ],
)
def test_status_resolved_commit_failure_resumes_without_vendor_requery_or_submission(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
    vendor_status: VendorTransactionStatus,
    expected_state: TransactionState,
):
    transaction = make_transaction()
    transaction.idempotency_key = f"resolved-resume-{uuid4()}"
    transaction.state = TransactionState.UNKNOWN
    postgres_session.add(transaction)
    postgres_session.commit()
    persisted_transaction_ids.append(transaction.id)

    class CountingRecoveryAdapter(FailingExecutionAdapter):
        def __init__(self) -> None:
            self.execution_count = 0
            self.query_count = 0

        def execute_transaction(
            self, request: TransactionExecutionRequest
        ) -> VendorTransactionResult:
            self.execution_count += 1
            return super().execute_transaction(request)

        def query_transaction(
            self, request: TransactionQueryRequest
        ) -> VendorTransactionResult:
            self.query_count += 1
            return VendorTransactionResult(
                status=vendor_status,
                vendor_reference=f"resolved-{request.transaction_id}",
                message=(
                    "Vendor confirmed failure"
                    if vendor_status == VendorTransactionStatus.FAILED
                    else None
                ),
                raw_response={"status": vendor_status.value},
            )

    adapter = CountingRecoveryAdapter()
    fail_terminal_commit = False
    original_commit = postgres_session.commit

    def commit_with_failure() -> None:
        nonlocal fail_terminal_commit
        if fail_terminal_commit:
            fail_terminal_commit = False
            postgres_session.rollback()
            raise RuntimeError("simulated local result commit failure")
        original_commit()

    monkeypatch.setattr(postgres_session, "commit", commit_with_failure)

    class FailAfterResolutionPersisted(PersistedTransactionExecutionService):
        def _transition_state(
            self,
            transaction: Transaction,
            expected: TransactionState,
            target: TransactionState,
            **values: object,
        ) -> bool:
            nonlocal fail_terminal_commit
            changed = super()._transition_state(
                transaction,
                expected,
                target,
                **values,
            )
            if (
                expected == TransactionState.INVESTIGATING
                and target == TransactionState.STATUS_RESOLVED
            ):
                fail_terminal_commit = True
            return changed

    with pytest.raises(RuntimeError, match="simulated local result commit failure"):
        FailAfterResolutionPersisted(
            postgres_session,
            TransactionExecutionService(adapter),
        ).execute(
            make_transaction_with_key(
                transaction.idempotency_key or "",
                beneficiary=transaction.beneficiary or "",
            )
        )

    assert adapter.execution_count == 0
    assert adapter.query_count == 1
    resolved = postgres_session.get(Transaction, transaction.id)
    assert resolved is not None
    assert resolved.state == TransactionState.STATUS_RESOLVED
    assert (
        resolved.error_message is None
        if vendor_status == VendorTransactionStatus.SUCCESS
        else resolved.error_message == "Vendor confirmed failure"
    )

    recovery_session = SessionLocal()
    try:
        resumed = PersistedTransactionExecutionService(
            recovery_session,
            TransactionExecutionService(adapter),
        ).execute(
            make_transaction_with_key(
                transaction.idempotency_key or "",
                beneficiary=transaction.beneficiary or "",
            )
        )
        assert resumed.id == transaction.id
        assert resumed.state == expected_state
    finally:
        recovery_session.close()

    assert adapter.execution_count == 0
    assert adapter.query_count == 1


def test_vendor_timeout_after_durable_submission_recovers_by_query(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    class TimeoutAfterSubmissionAdapter(VendorAAdapter):
        def __init__(self) -> None:
            super().__init__(PostgresVendorAOperationLedger(SessionLocal))
            self.execution_count = 0
            self.query_count = 0

        def execute_transaction(
            self, request: TransactionExecutionRequest
        ) -> VendorTransactionResult:
            self.execution_count += 1
            super().execute_transaction(request)
            raise TimeoutError("simulated response timeout")

        def query_transaction(
            self, request: TransactionQueryRequest
        ) -> VendorTransactionResult:
            self.query_count += 1
            return super().query_transaction(request)

    adapter = TimeoutAfterSubmissionAdapter()
    adapter.authenticate(AuthenticationRequest({"api_key": "vendor_a_test_key"}))
    transaction = make_transaction()
    transaction.idempotency_key = f"timeout-recovery-{uuid4()}"
    result = PersistedTransactionExecutionService(
        postgres_session,
        TransactionExecutionService(adapter),
    ).execute(transaction)
    persisted_transaction_ids.append(result.id)

    assert result.state == TransactionState.SUCCESS
    assert adapter.execution_count == 1
    assert adapter.query_count == 1


def test_not_found_during_requery_remains_unknown_without_submission(
    postgres_session: Session,
    persisted_transaction_ids: list[UUID],
):
    class QueryOnlyAdapter(FailingExecutionAdapter):
        def __init__(self) -> None:
            self.execution_count = 0
            self.query_count = 0

        def execute_transaction(
            self, request: TransactionExecutionRequest
        ) -> VendorTransactionResult:
            self.execution_count += 1
            return super().execute_transaction(request)

        def query_transaction(
            self, request: TransactionQueryRequest
        ) -> VendorTransactionResult:
            self.query_count += 1
            return VendorTransactionResult(
                status=VendorTransactionStatus.UNKNOWN,
                message="operation not found",
            )

    transaction = make_transaction()
    transaction.idempotency_key = f"missing-operation-{uuid4()}"
    transaction.state = TransactionState.SUBMITTING
    postgres_session.add(transaction)
    postgres_session.commit()
    persisted_transaction_ids.append(transaction.id)
    adapter = QueryOnlyAdapter()

    result = PersistedTransactionExecutionService(
        postgres_session,
        TransactionExecutionService(adapter),
    ).execute(make_transaction_with_key(
        transaction.idempotency_key or "",
        beneficiary=transaction.beneficiary or "",
    ))

    assert result.state == TransactionState.UNKNOWN
    assert adapter.execution_count == 0
    assert adapter.query_count == 1


def make_transaction_with_key(key: str, *, beneficiary: str) -> Transaction:
    transaction = make_transaction(beneficiary=beneficiary)
    transaction.idempotency_key = key
    return transaction
