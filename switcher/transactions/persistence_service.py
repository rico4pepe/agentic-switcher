"""Persistence boundary for idempotent transaction execution and recovery."""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.domain.transaction import Transaction, TransactionState
from switcher.transactions.execution_service import (
    TransactionExecutionService,
    VendorSubmissionUncertain,
)
from vendors.base.models import VendorTransactionStatus


logger = logging.getLogger(__name__)


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused for different business inputs."""


#: States in which a vendor operation may still be executing, or may already
#: have executed without a confirmed outcome. Every non-terminal state belongs
#: here:
#:
#: * ``SUBMITTING``/``SUBMITTED``/``UNKNOWN``/``INVESTIGATING``/``STATUS_RESOLVED``
#:   may represent a purchase the vendor has performed or is performing.
#: * ``CREATED``/``VALIDATING``/``VALIDATED`` are committed rows that will
#:   proceed to submission. They must match too, otherwise two concurrent
#:   equivalent requests would each create and submit their own operation.
#:
#: ``SUCCESS`` and ``FAILED`` are terminal, so a later purchase with the same
#: inputs remains legitimate. There is deliberately no age cut-off: an
#: ``UNKNOWN`` outcome is never assumed to be a failure (ADR-003).
UNRESOLVED_STATES: frozenset[TransactionState] = frozenset(
    {
        TransactionState.CREATED,
        TransactionState.VALIDATING,
        TransactionState.VALIDATED,
        TransactionState.SUBMITTING,
        TransactionState.SUBMITTED,
        TransactionState.UNKNOWN,
        TransactionState.INVESTIGATING,
        TransactionState.STATUS_RESOLVED,
    }
)

#: Safe, client-facing diagnostic recorded when the vendor status query itself
#: raised. The exception text is never persisted or returned (it may contain
#: hostnames or credentials); it is logged server-side only.
STATUS_QUERY_FAILED_CODE = "STATUS_QUERY_FAILED"
STATUS_QUERY_FAILED_MESSAGE = (
    "Vendor status could not be queried; the outcome is unconfirmed"
)

_EQUIVALENCE_LOCK_NAMESPACE = "switcher:equivalent-unresolved-operation:v1"
_AMOUNT_QUANTUM = Decimal("0.01")


class ExecutionMatch(StrEnum):
    """How an execution request relates to previously persisted operations."""

    NEW = "new"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    EQUIVALENT_UNRESOLVED = "equivalent_unresolved"


@dataclass(frozen=True)
class ExecutionOutcome:
    """The canonical transaction and whether it pre-existed this request."""

    transaction: Transaction
    match: ExecutionMatch


@dataclass(frozen=True)
class EquivalenceKey:
    """Normalized persisted business fields identifying one requested operation.

    Deliberately excludes the idempotency key, generated ids, timestamps,
    vendor choice, and any planner or chat wording.
    """

    product_type: str
    network: str | None
    beneficiary: str | None
    amount: Decimal

    @classmethod
    def from_transaction(cls, transaction: Transaction) -> "EquivalenceKey":
        return cls(
            product_type=_normalize_text(transaction.product_type) or "",
            network=_normalize_text(transaction.network),
            beneficiary=_normalize_text(transaction.beneficiary),
            amount=Decimal(transaction.amount).quantize(
                _AMOUNT_QUANTUM,
                rounding=ROUND_HALF_UP,
            ),
        )

    def lock_key(self) -> int:
        """Return a stable signed 64-bit key for ``pg_advisory_xact_lock``."""
        canonical = "\x1f".join(
            (
                _EQUIVALENCE_LOCK_NAMESPACE,
                self.product_type,
                self.network if self.network is not None else "\x00",
                self.beneficiary if self.beneficiary is not None else "\x00",
                str(self.amount),
            )
        )
        digest = hashlib.blake2b(canonical.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big", signed=True)


def _normalize_text(value: str | None) -> str | None:
    return None if value is None else value.strip().lower()


class PersistedTransactionExecutionService:
    """Persist operation identity before submission and recover without retries."""

    def __init__(
        self,
        session: Session,
        execution_service: (
            TransactionExecutionService | Callable[[], TransactionExecutionService]
        ),
        *,
        vendor_execution_service_factory: (
            Callable[[str], TransactionExecutionService] | None
        ) = None,
    ) -> None:
        """Create the service.

        ``vendor_execution_service_factory`` builds the execution service for a
        specific vendor code. It lets an equivalent unresolved operation be
        reconciled through the vendor that already owns it, instead of whichever
        vendor the new request happened to be routed to.
        """
        self._session = session
        self._vendor_execution_service_factory = vendor_execution_service_factory
        self._execution_service = (
            execution_service
            if isinstance(execution_service, TransactionExecutionService)
            else None
        )
        self._execution_service_factory = (
            None
            if isinstance(execution_service, TransactionExecutionService)
            else execution_service
        )

    def execute(self, transaction: Transaction) -> Transaction:
        """Execute a new operation, reuse a keyed one, or reconcile its status."""
        return self.execute_with_outcome(transaction).transaction

    def execute_with_outcome(self, transaction: Transaction) -> ExecutionOutcome:
        """Like :meth:`execute`, but also report how the request was matched.

        Order of checks:

        1. Same idempotency key: replay (or conflict if inputs differ).
        2. Otherwise, under a transaction-scoped advisory lock, an equivalent
           *unresolved* operation is returned/reconciled instead of creating a
           second vendor operation.
        3. Otherwise a new transaction is persisted and executed.
        """
        if transaction.idempotency_key is not None:
            existing = self._find_by_idempotency_key(transaction.idempotency_key)
            if existing is not None:
                self._assert_same_business_inputs(existing, transaction)
                return ExecutionOutcome(
                    self._resume(existing),
                    ExecutionMatch.IDEMPOTENT_REPLAY,
                )

        transaction.id = transaction.id or uuid4()
        self._get_execution_service()
        try:
            equivalent = self._insert_unless_equivalent_unresolved(transaction)
        except IntegrityError:
            self._session.rollback()
            if transaction.idempotency_key is None:
                raise
            existing = self._find_by_idempotency_key(transaction.idempotency_key)
            if existing is None:
                raise
            self._assert_same_business_inputs(existing, transaction)
            return ExecutionOutcome(
                self._resume(existing),
                ExecutionMatch.IDEMPOTENT_REPLAY,
            )

        if equivalent is not None:
            # A concurrent request with the *same* key may have won the race to
            # insert; that is still an idempotent replay, not a duplicate.
            same_key = (
                transaction.idempotency_key is not None
                and equivalent.idempotency_key == transaction.idempotency_key
            )
            return ExecutionOutcome(
                self._resume_equivalent(equivalent, requested=transaction),
                (
                    ExecutionMatch.IDEMPOTENT_REPLAY
                    if same_key
                    else ExecutionMatch.EQUIVALENT_UNRESOLVED
                ),
            )

        self._session.refresh(transaction)
        return ExecutionOutcome(self._resume(transaction), ExecutionMatch.NEW)

    def _insert_unless_equivalent_unresolved(
        self,
        transaction: Transaction,
    ) -> Transaction | None:
        """Atomically find an equivalent unresolved operation or insert this one.

        A transaction-scoped advisory lock keyed on the normalized business
        fields serializes concurrent equivalent requests around the
        check-then-insert only. The lock is released by the commit/rollback
        below, before any vendor call is made, so it is never held across slow
        network I/O. Different operations hash to different locks and do not
        contend.
        """
        key = EquivalenceKey.from_transaction(transaction)
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": key.lock_key()},
        )
        equivalent = self._find_equivalent_unresolved(key)
        if equivalent is not None:
            # Nothing to write; end the transaction to release the lock.
            self._session.rollback()
            return equivalent

        self._session.add(transaction)
        self._session.commit()
        return None

    def _find_equivalent_unresolved(self, key: EquivalenceKey) -> Transaction | None:
        return self._session.scalar(
            select(Transaction)
            .where(
                Transaction.state.in_(UNRESOLVED_STATES),
                func.lower(func.btrim(Transaction.product_type))
                == key.product_type,
                func.lower(func.btrim(Transaction.network)).is_not_distinct_from(
                    key.network
                ),
                func.lower(func.btrim(Transaction.beneficiary)).is_not_distinct_from(
                    key.beneficiary
                ),
                Transaction.amount == key.amount,
            )
            .order_by(Transaction.created_at.asc(), Transaction.id.asc())
            .limit(1)
        )

    def _resume_equivalent(
        self,
        existing: Transaction,
        *,
        requested: Transaction,
    ) -> Transaction:
        """Reconcile an existing unresolved operation through its own vendor.

        The existing operation is never re-routed to the vendor the new request
        would have chosen. If that vendor's service cannot be obtained, the
        existing record is returned untouched rather than queried elsewhere.
        """
        owner = existing.vendor_code
        # The request's vendor is stamped on its row by callers that route
        # first (MCP); otherwise it is whatever the configured service speaks.
        requested_vendor = (
            requested.vendor_code or self._get_execution_service().vendor_code()
        )
        if owner is None or owner == requested_vendor:
            return self._resume(existing)
        if self._vendor_execution_service_factory is None:
            self._refresh(existing)
            return existing
        owner_service = PersistedTransactionExecutionService(
            self._session,
            self._vendor_execution_service_factory(owner),
            vendor_execution_service_factory=self._vendor_execution_service_factory,
        )
        return owner_service._resume(existing)

    def investigate(self, transaction: Transaction) -> Transaction:
        """Query the vendor for a transaction that is awaiting status resolution."""
        if transaction.id is None:
            raise ValueError("Transaction identity must exist before status query")
        if transaction.state not in {
            TransactionState.UNKNOWN,
            TransactionState.SUBMITTING,
            TransactionState.SUBMITTED,
            TransactionState.INVESTIGATING,
            TransactionState.STATUS_RESOLVED,
        }:
            raise ValueError("Transaction is not eligible for status investigation")
        return self._resume(transaction)

    def _resume(self, transaction: Transaction) -> Transaction:
        validated_by_this_adapter = False
        while True:
            self._refresh(transaction)
            state = transaction.state

            if state in {TransactionState.SUCCESS, TransactionState.FAILED}:
                return transaction

            if state == TransactionState.STATUS_RESOLVED:
                target_state = (
                    TransactionState.SUCCESS
                    if transaction.error_message is None
                    else TransactionState.FAILED
                )
                self._transition_state(
                    transaction,
                    TransactionState.STATUS_RESOLVED,
                    target_state,
                )
                continue

            if state in {
                TransactionState.CREATED,
                TransactionState.VALIDATING,
            }:
                if state == TransactionState.CREATED and not self._transition_state(
                    transaction,
                    TransactionState.CREATED,
                    TransactionState.VALIDATING,
                ):
                    continue
                execution_service = self._get_execution_service()
                validation = execution_service.validate(transaction)
                validation_values: dict[str, object] = {
                    "vendor_code": execution_service.vendor_code(),
                }
                if validation.is_valid:
                    target_state = TransactionState.VALIDATED
                    validated_by_this_adapter = True
                else:
                    target_state = TransactionState.FAILED
                    validation_values["error_message"] = (
                        validation.message or "Customer validation failed"
                    )
                if not self._transition_state(
                    transaction,
                    TransactionState.VALIDATING,
                    target_state,
                    **validation_values,
                ):
                    continue
                continue

            if state == TransactionState.VALIDATED:
                if not validated_by_this_adapter:
                    execution_service = self._get_execution_service()
                    validation = execution_service.validate(transaction)
                    if not validation.is_valid:
                        self._transition_state(
                            transaction,
                            TransactionState.VALIDATED,
                            TransactionState.FAILED,
                            error_message=(
                                validation.message or "Customer validation failed"
                            ),
                        )
                        continue
                    validated_by_this_adapter = True
                if self._transition_state(
                    transaction,
                    TransactionState.VALIDATED,
                    TransactionState.SUBMITTING,
                ):
                    return self._submit(transaction)
                continue

            if state in {
                TransactionState.SUBMITTING,
                TransactionState.SUBMITTED,
                TransactionState.UNKNOWN,
                TransactionState.INVESTIGATING,
                TransactionState.STATUS_RESOLVED,
            }:
                return self._reconcile(transaction)

            return transaction

    def _transition_state(
        self,
        transaction: Transaction,
        expected: TransactionState,
        target: TransactionState,
        **values: object,
    ) -> bool:
        result = self._session.execute(
            update(Transaction)
            .where(
                Transaction.id == transaction.id,
                Transaction.state == expected,
            )
            .values(state=target, **values)
            .execution_options(synchronize_session=False)
        )
        self._session.commit()
        self._refresh(transaction)
        return result.rowcount == 1

    def _refresh(self, transaction: Transaction) -> None:
        self._session.expire(transaction)
        self._session.refresh(transaction)

    def _submit(self, transaction: Transaction) -> Transaction:
        try:
            result = self._get_execution_service().submit(transaction)
        except VendorSubmissionUncertain as error:
            self._transition_state(
                transaction,
                TransactionState.SUBMITTING,
                TransactionState.UNKNOWN,
                error_message=str(error),
            )
            return self._reconcile(transaction)

        result_values: dict[str, object] = {
            "vendor_reference": result.vendor_reference,
            "raw_vendor_response": (
                dict(result.raw_response) if result.raw_response is not None else None
            ),
        }
        if result.status == VendorTransactionStatus.SUCCESS:
            if not self._transition_state(
                transaction,
                TransactionState.SUBMITTING,
                TransactionState.SUBMITTED,
                **result_values,
            ):
                return self._resume(transaction)
            self._transition_state(
                transaction,
                TransactionState.SUBMITTED,
                TransactionState.SUCCESS,
            )
        elif result.status == VendorTransactionStatus.FAILED:
            self._transition_state(
                transaction,
                TransactionState.SUBMITTING,
                TransactionState.FAILED,
                error_message=result.message or "Vendor execution failed",
                **result_values,
            )
        elif result.status == VendorTransactionStatus.ACCEPTED:
            self._transition_state(
                transaction,
                TransactionState.SUBMITTING,
                TransactionState.SUBMITTED,
                **result_values,
            )
        else:
            self._transition_state(
                transaction,
                TransactionState.SUBMITTING,
                TransactionState.UNKNOWN,
                error_message=result.message,
                **result_values,
            )

        self._refresh(transaction)
        return transaction

    def _reconcile(self, transaction: Transaction) -> Transaction:
        if transaction.id is None:
            raise ValueError("Transaction identity must exist before status query")

        # Resolve the vendor service before touching persisted state, so a
        # failure to build/authenticate an adapter cannot strand the row in
        # INVESTIGATING.
        execution_service = self._get_execution_service()

        if transaction.state in {
            TransactionState.SUBMITTING,
            TransactionState.SUBMITTED,
        }:
            self._transition_state(
                transaction,
                transaction.state,
                TransactionState.UNKNOWN,
            )

        self._refresh(transaction)
        if transaction.state == TransactionState.UNKNOWN:
            self._transition_state(
                transaction,
                TransactionState.UNKNOWN,
                TransactionState.INVESTIGATING,
            )
        self._refresh(transaction)
        if transaction.state != TransactionState.INVESTIGATING:
            return transaction

        try:
            result = execution_service.query(transaction)
        except Exception as error:  # noqa: BLE001 - any vendor/query failure
            return self._record_status_query_failure(transaction, error)
        result_values: dict[str, object] = {
            "vendor_reference": result.vendor_reference,
            "raw_vendor_response": (
                dict(result.raw_response) if result.raw_response is not None else None
            ),
            # The query itself succeeded, so any earlier query-failure marker
            # is no longer current.
            "error_code": None,
        }
        if result.status == VendorTransactionStatus.SUCCESS:
            if self._transition_state(
                transaction,
                TransactionState.INVESTIGATING,
                TransactionState.STATUS_RESOLVED,
                error_message=None,
                **result_values,
            ):
                self._transition_state(
                    transaction,
                    TransactionState.STATUS_RESOLVED,
                    TransactionState.SUCCESS,
                )
        elif result.status == VendorTransactionStatus.FAILED:
            if self._transition_state(
                transaction,
                TransactionState.INVESTIGATING,
                TransactionState.STATUS_RESOLVED,
                error_message=result.message or "Vendor execution failed",
                **result_values,
            ):
                self._transition_state(
                    transaction,
                    TransactionState.STATUS_RESOLVED,
                    TransactionState.FAILED,
                )
        else:
            self._transition_state(
                transaction,
                TransactionState.INVESTIGATING,
                TransactionState.UNKNOWN,
                error_message=result.message,
                **result_values,
            )

        self._refresh(transaction)
        return transaction

    def _record_status_query_failure(
        self,
        transaction: Transaction,
        error: Exception,
    ) -> Transaction:
        """Keep an unconfirmed transaction UNKNOWN after its status query failed.

        The transaction id, vendor identity, vendor reference and raw vendor
        response are left untouched. Nothing is resubmitted and no terminal
        outcome is claimed. The exception is logged server-side only; clients
        see just a static, secret-free code and message.
        """
        logger.warning(
            "Vendor status query failed; transaction remains unresolved "
            "(transaction_id=%s vendor_code=%s error_type=%s)",
            transaction.id,
            transaction.vendor_code,
            type(error).__name__,
            exc_info=error,
        )
        self._transition_state(
            transaction,
            TransactionState.INVESTIGATING,
            TransactionState.UNKNOWN,
            error_code=STATUS_QUERY_FAILED_CODE,
            # Keep the original reason this transaction became uncertain.
            error_message=func.coalesce(
                Transaction.error_message,
                STATUS_QUERY_FAILED_MESSAGE,
            ),
        )
        self._refresh(transaction)
        return transaction

    def _get_execution_service(self) -> TransactionExecutionService:
        if self._execution_service is None:
            if self._execution_service_factory is None:
                raise RuntimeError("Transaction execution service is unavailable")
            self._execution_service = self._execution_service_factory()
        return self._execution_service

    def _find_by_idempotency_key(self, idempotency_key: str) -> Transaction | None:
        return self._session.scalar(
            select(Transaction).where(
                Transaction.idempotency_key == idempotency_key,
            )
        )

    @staticmethod
    def _assert_same_business_inputs(
        existing: Transaction,
        requested: Transaction,
    ) -> None:
        same_inputs = (
            existing.product_type == requested.product_type
            and existing.network == requested.network
            and existing.beneficiary == requested.beneficiary
            and existing.amount == requested.amount
        )
        if not same_inputs:
            raise IdempotencyConflictError(
                "Idempotency key is already associated with different transaction inputs"
            )
