"""Focused tests for the deterministic Vendor A adapter."""

from decimal import Decimal
from uuid import uuid4

from vendors.base.models import (
    AuthenticationRequest,
    CustomerValidationRequest,
    TransactionExecutionRequest,
    TransactionQueryRequest,
    VendorOperation,
    VendorTransactionStatus,
)
from vendors.vendor_a import VendorAAdapter


def authenticated_adapter() -> VendorAAdapter:
    """Create an adapter with Vendor A's supported test credential."""
    adapter = VendorAAdapter()
    adapter.authenticate(AuthenticationRequest({"api_key": "vendor_a_test_key"}))
    return adapter


def valid_validation_request() -> CustomerValidationRequest:
    """Build the deterministic valid Vendor A validation request."""
    return CustomerValidationRequest(
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
    )


def valid_execution_request() -> TransactionExecutionRequest:
    """Build a supported Vendor A airtime execution request."""
    return TransactionExecutionRequest(
        transaction_id=uuid4(),
        product_type="airtime",
        network="MTN",
        beneficiary="08030000000",
        amount=Decimal("5000.00"),
    )


def test_vendor_a_capabilities_describe_mtn_airtime_validation_workflow():
    capabilities = VendorAAdapter().get_capabilities()

    assert capabilities.vendor_code == "vendor_a"
    assert capabilities.supported_product_types == frozenset({"airtime"})
    assert capabilities.requires_customer_validation
    assert all(capabilities.supports(operation) for operation in VendorOperation)


def test_vendor_a_authentication_accepts_supported_test_credential():
    result = VendorAAdapter().authenticate(
        AuthenticationRequest({"api_key": "vendor_a_test_key"})
    )

    assert result.authenticated
    assert result.message is None


def test_vendor_a_requires_customer_validation_before_execution():
    result = authenticated_adapter().execute_transaction(valid_execution_request())

    assert result.status == VendorTransactionStatus.FAILED
    assert result.message == "Customer validation is required before execution"


def test_vendor_a_validates_supported_customer():
    result = authenticated_adapter().validate_customer(valid_validation_request())

    assert result.is_valid
    assert result.customer_name == "Ada Okafor"


def test_vendor_a_rejects_invalid_customer():
    result = authenticated_adapter().validate_customer(
        CustomerValidationRequest(
            product_type="airtime",
            network="MTN",
            beneficiary="08039999999",
        )
    )

    assert not result.is_valid
    assert result.message == "Customer is not valid for Vendor A MTN airtime"


def test_vendor_a_executes_validated_airtime_transaction_successfully():
    adapter = authenticated_adapter()
    adapter.validate_customer(valid_validation_request())

    result = adapter.execute_transaction(valid_execution_request())

    assert result.status == VendorTransactionStatus.SUCCESS
    assert result.vendor_reference is not None
    assert result.vendor_reference.startswith("vendor_a-")


def test_vendor_a_queries_successful_transaction():
    adapter = authenticated_adapter()
    adapter.validate_customer(valid_validation_request())
    execution = adapter.execute_transaction(valid_execution_request())

    result = adapter.query_transaction(
        TransactionQueryRequest(execution.vendor_reference or "")
    )

    assert result == execution


def test_vendor_a_returns_unknown_for_unknown_vendor_reference():
    result = VendorAAdapter().query_transaction(
        TransactionQueryRequest("vendor_a-not-found")
    )

    assert result.status == VendorTransactionStatus.UNKNOWN
    assert result.vendor_reference == "vendor_a-not-found"
