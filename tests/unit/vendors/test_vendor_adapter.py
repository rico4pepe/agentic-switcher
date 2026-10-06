"""Contract tests for the vendor adapter boundary."""

import ast
import inspect
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

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


class DummyAirtimeVendor(VendorAdapter):
    """Minimal no-validation vendor used only by these contract tests."""

    def authenticate(self, request: AuthenticationRequest) -> AuthenticationResult:
        return AuthenticationResult(authenticated=bool(request.credentials))

    def get_capabilities(self) -> VendorCapabilities:
        return VendorCapabilities(
            vendor_code="dummy-airtime",
            supported_product_types=frozenset({"airtime"}),
            supported_operations=frozenset(
                {
                    VendorOperation.AUTHENTICATE,
                    VendorOperation.GET_CAPABILITIES,
                    VendorOperation.EXECUTE_TRANSACTION,
                    VendorOperation.QUERY_TRANSACTION,
                }
            ),
        )

    def validate_customer(
        self, request: CustomerValidationRequest
    ) -> CustomerValidationResult:
        raise VendorOperationUnsupported(VendorOperation.VALIDATE_CUSTOMER)

    def execute_transaction(
        self, request: TransactionExecutionRequest
    ) -> VendorTransactionResult:
        return VendorTransactionResult(
            status=VendorTransactionStatus.ACCEPTED,
            vendor_reference=f"dummy-{request.transaction_id}",
        )

    def query_transaction(
        self, request: TransactionQueryRequest
    ) -> VendorTransactionResult:
        return VendorTransactionResult(
            status=VendorTransactionStatus.SUCCESS,
            vendor_reference=f"dummy-{request.transaction_id}",
        )


def test_contract_can_be_implemented_by_minimal_adapter():
    adapter = DummyAirtimeVendor()

    assert isinstance(adapter, VendorAdapter)
    assert adapter.authenticate(AuthenticationRequest({"api_key": "test"})).authenticated


def test_contract_represents_all_required_operations():
    required_operations = {
        "authenticate",
        "get_capabilities",
        "validate_customer",
        "execute_transaction",
        "query_transaction",
    }

    assert required_operations <= set(VendorAdapter.__abstractmethods__)
    assert {operation.value for operation in VendorOperation} == required_operations


def test_minimal_adapter_executes_and_queries_transaction():
    adapter = DummyAirtimeVendor()
    request = TransactionExecutionRequest(
            transaction_id=uuid4(),
            product_type="airtime",
            network="MTN",
            beneficiary="08030000000",
            amount=Decimal("5000.00"),
    )
    execution = adapter.execute_transaction(request)

    assert execution.status == VendorTransactionStatus.ACCEPTED
    assert adapter.query_transaction(
        TransactionQueryRequest(request.transaction_id)
    ).status == VendorTransactionStatus.SUCCESS


def test_optional_customer_validation_is_advertised_and_rejected_cleanly():
    adapter = DummyAirtimeVendor()

    assert not adapter.get_capabilities().supports(VendorOperation.VALIDATE_CUSTOMER)
    assert not adapter.get_capabilities().requires_customer_validation
    with pytest.raises(VendorOperationUnsupported) as error:
        adapter.validate_customer(
            CustomerValidationRequest(
                product_type="airtime",
                network="MTN",
                beneficiary="08030000000",
            )
        )
    assert error.value.operation == VendorOperation.VALIDATE_CUSTOMER


def test_adapter_layer_does_not_import_transaction_state_machine():
    adapter_directory = Path(inspect.getfile(VendorAdapter)).parent
    imported_modules = set()

    for source_file in adapter_directory.glob("*.py"):
        imports = ast.parse(source_file.read_text(encoding="utf-8"))
        imported_modules.update(
            node.module
            for node in ast.walk(imports)
            if isinstance(node, ast.ImportFrom) and node.module
        )

    assert "apps.api.app.domain.state_machine" not in imported_modules
