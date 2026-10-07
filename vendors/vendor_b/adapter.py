"""Deterministic simulated implementation of Vendor B."""

from apps.api.app.database import SessionLocal
from capabilities.domain import Capability, CapabilityOperation, WorkflowStep
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
from vendors.vendor_b.operation_ledger import (
    PostgresVendorBOperationLedger,
    VendorBOperationLedger,
)


class VendorBAdapter(VendorAdapter):
    """In-memory Vendor B simulator for MTN airtime transactions."""

    VENDOR_CODE = "vendor_b"
    PRODUCT_TYPE = "airtime"
    NETWORK = "MTN"
    _API_KEY = "vendor_b_test_key"
    _VALID_BENEFICIARY = "08030000001"
    _LEGACY_BENEFICIARY = "08030000000"
    _CUSTOMER_NAME = "Ngozi Okafor"

    def __init__(self, operation_ledger: VendorBOperationLedger | None = None) -> None:
        self._authenticated = False
        self._validated_beneficiaries: set[str] = set()
        self._operation_ledger = operation_ledger or PostgresVendorBOperationLedger(
            SessionLocal
        )

    def authenticate(self, request: AuthenticationRequest) -> AuthenticationResult:
        """Authenticate using Vendor B's deterministic test credential."""
        self._authenticated = request.credentials.get("api_key") == self._API_KEY
        if self._authenticated:
            return AuthenticationResult(authenticated=True)
        return AuthenticationResult(
            authenticated=False,
            message="Invalid Vendor B credentials",
        )

    def get_capabilities(self) -> VendorCapabilities:
        """Return adapter metadata derived from Vendor B's canonical capability."""
        capability = self.get_canonical_capability()
        return VendorCapabilities(
            vendor_code=capability.vendor_code,
            supported_product_types=frozenset({capability.product_type}),
            supported_operations=frozenset(
                {
                    *(VendorOperation(operation.value)
                      for operation in capability.supported_operations),
                    VendorOperation.GET_CAPABILITIES,
                }
            ),
            requires_customer_validation=any(
                step.operation == CapabilityOperation.VALIDATE_CUSTOMER
                and step.required
                for step in capability.workflow
            ),
        )

    def get_canonical_capability(self) -> Capability:
        """Describe Vendor B's offering using canonical business terminology."""
        return Capability(
            vendor_code=self.VENDOR_CODE,
            service_type="airtime",
            product_type=self.PRODUCT_TYPE,
            network=self.NETWORK,
            supported_operations=frozenset(CapabilityOperation),
            workflow=(
                WorkflowStep(CapabilityOperation.AUTHENTICATE, required=True),
                WorkflowStep(CapabilityOperation.VALIDATE_CUSTOMER, required=True),
                WorkflowStep(CapabilityOperation.EXECUTE_TRANSACTION, required=True),
                WorkflowStep(CapabilityOperation.QUERY_TRANSACTION, required=True),
            ),
        )

    def validate_customer(
        self, request: CustomerValidationRequest
    ) -> CustomerValidationResult:
        """Validate the single deterministic customer accepted by Vendor B."""
        if not self._authenticated:
            return CustomerValidationResult(
                is_valid=False,
                message="Vendor B authentication is required",
            )

        is_valid = (
            request.product_type == self.PRODUCT_TYPE
            and request.network == self.NETWORK
            and request.beneficiary in {self._VALID_BENEFICIARY, self._LEGACY_BENEFICIARY}
        )
        if not is_valid:
            return CustomerValidationResult(
                is_valid=False,
                message="Customer is not valid for Vendor B MTN airtime",
            )

        self._validated_beneficiaries.add(request.beneficiary)
        return CustomerValidationResult(
            is_valid=True,
            customer_name=self._CUSTOMER_NAME,
        )

    def execute_transaction(
        self, request: TransactionExecutionRequest
    ) -> VendorTransactionResult:
        """Execute a validated MTN airtime transaction deterministically."""
        if not self._authenticated:
            return VendorTransactionResult(
                status=VendorTransactionStatus.FAILED,
                message="Vendor B authentication is required",
            )
        if request.beneficiary not in self._validated_beneficiaries:
            return VendorTransactionResult(
                status=VendorTransactionStatus.FAILED,
                message="Customer validation is required before execution",
            )
        if (
            request.product_type != self.PRODUCT_TYPE
            or request.network != self.NETWORK
        ):
            return VendorTransactionResult(
                status=VendorTransactionStatus.FAILED,
                message="Vendor B supports MTN airtime only",
            )

        return self._operation_ledger.submit(request)

    def query_transaction(
        self, request: TransactionQueryRequest
    ) -> VendorTransactionResult:
        """Query the vendor-owned durable ledger without submitting an operation."""
        return self._operation_ledger.query(request.transaction_id)
