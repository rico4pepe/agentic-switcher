"""Shared contracts for vendor adapters."""

from vendors.base.adapter import VendorAdapter, VendorOperationUnsupported
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

__all__ = [
    "AuthenticationRequest",
    "AuthenticationResult",
    "CustomerValidationRequest",
    "CustomerValidationResult",
    "TransactionExecutionRequest",
    "TransactionQueryRequest",
    "VendorAdapter",
    "VendorCapabilities",
    "VendorOperation",
    "VendorOperationUnsupported",
    "VendorTransactionResult",
    "VendorTransactionStatus",
]
