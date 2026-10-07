"""Persistence boundary for idempotent transaction execution and recovery."""

from collections.abc import Callable
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.domain.transaction import Transaction, TransactionState
from switcher.transactions.execution_service import (
    TransactionExecutionService,
    VendorSubmissionUncertain,
)
from vendors.base.models import VendorTransactionStatus


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused for different business inputs."""


class PersistedTransactionExecutionService:
    """Persist operation identity before submission and recover without retries."""

    def __init__(
        self,
        session: Session,
        execution_service: (
            TransactionExecutionService | Callable[[], TransactionExecutionService]
        ),
    ) -> None:
        self._session = session
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
        if transaction.idempotency_key is not None:
            existing = self._find_by_idempotency_key(transaction.idempotency_key)
            if existing is not None:
                self._assert_same_business_inputs(existing, transaction)
                return self._resume(existing)

        transaction.id = transaction.id or uuid4()
        self._get_execution_service()
        self._session.add(transaction)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if transaction.idempotency_key is None:
                raise
            existing = self._find_by_idempotency_key(transaction.idempotency_key)
            if existing is None:
                raise
            self._assert_same_business_inputs(existing, transaction)
            return self._resume(existing)

        self._session.refresh(transaction)
        return self._resume(transaction)

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

        execution_service = self._get_execution_service()
        result = execution_service.query(transaction)
        result_values: dict[str, object] = {
            "vendor_reference": result.vendor_reference,
            "raw_vendor_response": (
                dict(result.raw_response) if result.raw_response is not None else None
            ),
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
