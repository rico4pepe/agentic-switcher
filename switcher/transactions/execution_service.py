"""In-memory execution of a Switcher transaction through a vendor adapter."""

from uuid import uuid4

from apps.api.app.domain.transaction import Transaction, TransactionState
from vendors.base.adapter import VendorAdapter
from vendors.base.models import (
    CustomerValidationRequest,
    TransactionExecutionRequest,
    VendorTransactionResult,
    VendorTransactionStatus,
)


class TransactionExecutionService:
    """Execute the validation and submission path for one transaction."""

    def __init__(self, adapter: VendorAdapter) -> None:
        self._adapter = adapter

    def execute(self, transaction: Transaction) -> Transaction:
        """Validate and submit a transaction, updating it in memory."""
        if transaction.id is None:
            transaction.id = uuid4()

        transaction.transition_to(TransactionState.VALIDATING)
        validation = self._adapter.validate_customer(
            CustomerValidationRequest(
                product_type=transaction.product_type,
                network=transaction.network,
                beneficiary=transaction.beneficiary or "",
            )
        )
        if not validation.is_valid:
            transaction.error_message = validation.message or "Customer validation failed"
            transaction.transition_to(TransactionState.FAILED)
            return transaction

        transaction.transition_to(TransactionState.VALIDATED)
        transaction.transition_to(TransactionState.SUBMITTED)
        result = self._adapter.execute_transaction(
            TransactionExecutionRequest(
                transaction_id=transaction.id,
                product_type=transaction.product_type,
                network=transaction.network,
                beneficiary=transaction.beneficiary or "",
                amount=transaction.amount,
            )
        )
        self._record_vendor_result(transaction, result)

        if result.status == VendorTransactionStatus.SUCCESS:
            transaction.transition_to(TransactionState.SUCCESS)
        elif result.status == VendorTransactionStatus.FAILED:
            transaction.error_message = result.message or "Vendor execution failed"
            transaction.transition_to(TransactionState.FAILED)
        else:
            raise ValueError(f"Unsupported vendor execution status: {result.status.value}")

        return transaction

    @staticmethod
    def _record_vendor_result(
        transaction: Transaction,
        result: VendorTransactionResult,
    ) -> None:
        """Copy vendor-owned execution details onto the canonical transaction."""
        transaction.vendor_reference = result.vendor_reference
        if result.raw_response is not None:
            transaction.raw_vendor_response = dict(result.raw_response)
