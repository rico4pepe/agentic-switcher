"""Abstract contract for transaction vendor integrations."""

from abc import ABC, abstractmethod

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
)


class VendorOperationUnsupported(NotImplementedError):
    """Raised when an adapter operation is not offered by a vendor."""

    def __init__(self, operation: VendorOperation) -> None:
        super().__init__(f"Vendor does not support operation: {operation.value}")
        self.operation = operation


class VendorAdapter(ABC):
    """Port implemented by each vendor-specific integration.

    Every adapter exposes the same callable surface.  Its capabilities declare
    which optional operations are supported; unsupported calls raise
    :class:`VendorOperationUnsupported`.
    """

    @abstractmethod
    def authenticate(self, request: AuthenticationRequest) -> AuthenticationResult:
        """Authenticate with the vendor when its workflow requires it."""

    @abstractmethod
    def get_capabilities(self) -> VendorCapabilities:
        """Describe products and operations supported by this vendor."""

    @abstractmethod
    def validate_customer(
        self, request: CustomerValidationRequest
    ) -> CustomerValidationResult:
        """Validate a beneficiary, or raise when unsupported."""

    @abstractmethod
    def execute_transaction(
        self, request: TransactionExecutionRequest
    ) -> VendorTransactionResult:
        """Submit a transaction to the vendor."""

    @abstractmethod
    def query_transaction(
        self, request: TransactionQueryRequest
    ) -> VendorTransactionResult:
        """Retrieve vendor status for a prior transaction."""
