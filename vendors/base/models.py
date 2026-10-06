"""Transport-neutral request and response models for vendor adapters."""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Mapping
from uuid import UUID


class VendorOperation(str, Enum):
    """Operations a vendor adapter can advertise."""

    AUTHENTICATE = "authenticate"
    GET_CAPABILITIES = "get_capabilities"
    VALIDATE_CUSTOMER = "validate_customer"
    EXECUTE_TRANSACTION = "execute_transaction"
    QUERY_TRANSACTION = "query_transaction"


class VendorTransactionStatus(str, Enum):
    """Vendor-reported transaction outcomes, independent of Switcher state."""

    ACCEPTED = "accepted"
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VendorCapabilities:
    """Operations and product types exposed by a vendor."""

    vendor_code: str
    supported_operations: frozenset[VendorOperation]
    supported_product_types: frozenset[str] = field(default_factory=frozenset)
    requires_customer_validation: bool = False

    def supports(self, operation: VendorOperation) -> bool:
        """Return whether the vendor supports an operation."""
        return operation in self.supported_operations


@dataclass(frozen=True)
class AuthenticationRequest:
    """Credentials or identifying values required by a vendor."""

    credentials: Mapping[str, str]


@dataclass(frozen=True)
class AuthenticationResult:
    """Result of vendor authentication."""

    authenticated: bool
    message: str | None = None


@dataclass(frozen=True)
class CustomerValidationRequest:
    """Details used to validate a beneficiary for a product."""

    product_type: str
    beneficiary: str
    network: str | None = None


@dataclass(frozen=True)
class CustomerValidationResult:
    """Vendor result for beneficiary validation."""

    is_valid: bool
    customer_name: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class TransactionExecutionRequest:
    """Canonical execution input passed from Switcher to a vendor adapter."""

    transaction_id: UUID
    product_type: str
    beneficiary: str
    amount: Decimal
    network: str | None = None


@dataclass(frozen=True)
class TransactionQueryRequest:
    """Stable Switcher operation identity used to query a prior submission."""

    transaction_id: UUID


@dataclass(frozen=True)
class VendorTransactionResult:
    """Normalized vendor result for an execution or status query."""

    status: VendorTransactionStatus
    vendor_reference: str | None = None
    message: str | None = None
    raw_response: Mapping[str, object] | None = None
