"""Tests for the first in-memory Switcher transaction execution flow."""

from decimal import Decimal
from uuid import uuid4

import pytest

from apps.api.app.domain.state_machine import InvalidTransactionTransition
from apps.api.app.domain.transaction import Transaction, TransactionState
from switcher.transactions.execution_service import TransactionExecutionService
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
from vendors.vendor_a.operation_ledger import InMemoryVendorAOperationLedger


def make_transaction(*, beneficiary: str = "08030000000") -> Transaction:
    """Create an in-memory MTN airtime transaction."""
    return Transaction(
        product_type="airtime",
        network="MTN",
        beneficiary=beneficiary,
        amount=Decimal("5000.00"),
    )


def authenticated_vendor_a() -> VendorAAdapter:
    """Create Vendor A with its deterministic test authentication completed."""
    adapter = VendorAAdapter(InMemoryVendorAOperationLedger())
    adapter.authenticate(AuthenticationRequest({"api_key": "vendor_a_test_key"}))
    return adapter


class FailingExecutionAdapter(VendorAdapter):
    """Small fake adapter providing a deterministic execution failure."""

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


def test_successful_complete_transaction_uses_vendor_a():
    transaction = make_transaction()
    transaction.id = uuid4()
    service = TransactionExecutionService(authenticated_vendor_a())

    assert service.validate(transaction).is_valid
    transaction.transition_to(TransactionState.VALIDATING)
    transaction.transition_to(TransactionState.VALIDATED)
    transaction.transition_to(TransactionState.SUBMITTING)
    result = service.submit(transaction)
    service.record_vendor_result(transaction, result)
    transaction.transition_to(TransactionState.SUBMITTED)
    transaction.transition_to(TransactionState.SUCCESS)

    assert transaction.state == TransactionState.SUCCESS


def test_customer_validation_failure_marks_transaction_failed():
    transaction = make_transaction(beneficiary="08039999999")
    service = TransactionExecutionService(authenticated_vendor_a())

    result = service.validate(transaction)

    assert not result.is_valid
    assert result.message == "Customer is not valid for Vendor A MTN airtime"


def test_execution_failure_marks_transaction_failed_and_keeps_vendor_details():
    transaction = make_transaction()
    transaction.id = uuid4()
    service = TransactionExecutionService(FailingExecutionAdapter())

    assert service.validate(transaction).is_valid
    transaction.transition_to(TransactionState.VALIDATING)
    transaction.transition_to(TransactionState.VALIDATED)
    transaction.transition_to(TransactionState.SUBMITTING)
    result = service.submit(transaction)
    service.record_vendor_result(transaction, result)
    transaction.error_message = result.message
    transaction.transition_to(TransactionState.FAILED)

    assert transaction.state == TransactionState.FAILED
    assert transaction.error_message == "Vendor balance unavailable"
    assert transaction.raw_vendor_response == {"code": "INSUFFICIENT_BALANCE"}


def test_successful_execution_copies_vendor_reference_to_transaction():
    transaction = make_transaction()
    transaction.id = uuid4()
    service = TransactionExecutionService(authenticated_vendor_a())

    assert service.validate(transaction).is_valid
    transaction.transition_to(TransactionState.VALIDATING)
    transaction.transition_to(TransactionState.VALIDATED)
    transaction.transition_to(TransactionState.SUBMITTING)
    result = service.submit(transaction)
    service.record_vendor_result(transaction, result)

    assert transaction.vendor_reference == f"vendor_a-{transaction.id}"


def test_customer_validation_does_not_mutate_transaction_state():
    transaction = make_transaction()
    transaction.transition_to(TransactionState.VALIDATING)
    service = TransactionExecutionService(authenticated_vendor_a())

    result = service.validate(transaction)

    assert result.is_valid
    assert transaction.state == TransactionState.VALIDATING
