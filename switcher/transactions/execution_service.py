"""In-memory execution of a Switcher transaction through a vendor adapter."""

from apps.api.app.domain.transaction import Transaction, TransactionState
from vendors.base.adapter import VendorAdapter
from vendors.base.models import (
    CustomerValidationRequest,
    CustomerValidationResult,
    TransactionExecutionRequest,
    TransactionQueryRequest,
    VendorTransactionResult,
    VendorTransactionStatus,
)


class VendorSubmissionUncertain(RuntimeError):
    """Vendor submission raised after its side effect may have occurred."""


class TransactionExecutionService:
    """Run deterministic validation, submission, and vendor-status lookup."""

    def __init__(self, adapter: VendorAdapter) -> None:
        self._adapter = adapter

    def validate(self, transaction: Transaction) -> CustomerValidationResult:
        """Check a customer without mutating the persisted transaction state."""
        return self._adapter.validate_customer(
            CustomerValidationRequest(
                product_type=transaction.product_type,
                network=transaction.network,
                beneficiary=transaction.beneficiary or "",
            )
        )

    def vendor_code(self) -> str:
        """Return the application-selected adapter's vendor identifier."""
        return self._adapter.get_capabilities().vendor_code

    def submit(self, transaction: Transaction) -> VendorTransactionResult:
        """Submit once after the caller has durably recorded SUBMITTING."""
        if transaction.id is None:
            raise ValueError("Transaction identity must exist before submission")
        try:
            return self._adapter.execute_transaction(
                TransactionExecutionRequest(
                    transaction_id=transaction.id,
                    product_type=transaction.product_type,
                    network=transaction.network,
                    beneficiary=transaction.beneficiary or "",
                    amount=transaction.amount,
                )
            )
        except Exception as error:
            raise VendorSubmissionUncertain(
                "Vendor submission outcome is uncertain"
            ) from error

    def query(self, transaction: Transaction) -> VendorTransactionResult:
        """Re-query status using the durable transaction operation identity."""
        if transaction.id is None:
            raise ValueError("Transaction identity must exist before status query")
        return self._adapter.query_transaction(
            TransactionQueryRequest(transaction_id=transaction.id)
        )

    @staticmethod
    def record_vendor_result(
        transaction: Transaction,
        result: VendorTransactionResult,
    ) -> None:
        """Copy vendor-owned details onto the canonical transaction."""
        transaction.vendor_reference = result.vendor_reference
        if result.raw_response is not None:
            transaction.raw_vendor_response = dict(result.raw_response)
