"""Persistence boundary for executing a transaction through the Switcher."""

from sqlalchemy.orm import Session

from apps.api.app.domain.transaction import Transaction
from switcher.transactions.execution_service import TransactionExecutionService


class PersistedTransactionExecutionService:
    """Persist an initial transaction, execute it, and commit its final state."""

    def __init__(
        self,
        session: Session,
        execution_service: TransactionExecutionService,
    ) -> None:
        self._session = session
        self._execution_service = execution_service

    def execute(self, transaction: Transaction) -> Transaction:
        """Flush the initial record, execute it, and commit the final record."""
        self._session.add(transaction)
        self._session.flush()
        self._execution_service.execute(transaction)
        self._session.commit()
        self._session.refresh(transaction)
        return transaction
