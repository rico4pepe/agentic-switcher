"""Deterministic transaction investigation and status resolution services."""

from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from apps.api.app.domain.transaction import Transaction, TransactionState
from switcher.transactions.execution_service import TransactionExecutionService
from switcher.transactions.persistence_service import PersistedTransactionExecutionService


class TransactionStatusOutput(BaseModel):
    """Structured read-only status response for a persisted transaction."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    transaction_id: UUID
    status: str
    vendor_reference: str | None = None
    raw_vendor_response: dict[str, object] | None = None
    error_message: str | None = None


class TransactionInvestigator:
    """Investigate a persisted transaction through the existing reconciliation path."""

    def __init__(
        self,
        session: Session,
        execution_service: (
            TransactionExecutionService | Callable[[], TransactionExecutionService]
        ),
    ) -> None:
        self._session = session
        self._service = PersistedTransactionExecutionService(
            session,
            execution_service,
        )

    def investigate(self, transaction_id: UUID) -> Transaction:
        """Return the canonical transaction after status investigation completes."""
        transaction = self._session.get(Transaction, transaction_id)
        if transaction is None:
            raise LookupError(f"Transaction {transaction_id} does not exist")
        if transaction.state not in {
            TransactionState.UNKNOWN,
            TransactionState.SUBMITTING,
            TransactionState.SUBMITTED,
            TransactionState.INVESTIGATING,
            TransactionState.STATUS_RESOLVED,
        }:
            raise ValueError("Transaction is not eligible for status investigation")
        return self._service.investigate(transaction)
