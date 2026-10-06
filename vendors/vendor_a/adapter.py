"""Deterministic simulated implementation of Vendor A."""

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
from vendors.vendor_a.operation_ledger import (
    VendorAOperationLedger,
    PostgresVendorAOperationLedger,
)


class VendorAAdapter(VendorAdapter):
    """In-memory Vendor A simulator for MTN airtime transactions.

    Operation status is durably stored in PostgreSQL by default. Tests may inject
    an in-memory ledger to keep adapter behavior isolated.
    """

    VENDOR_CODE = "vendor_a"
    PRODUCT_TYPE = "airtime"
    NETWORK = "MTN"
    _API_KEY = "vendor_a_test_key"
    _VALID_BENEFICIARY = "08030000000"
    _CUSTOMER_NAME = "Ada Okafor"

    def __init__(self, operation_ledger: VendorAOperationLedger | None = None) -> None:
        self._authenticated = False
        self._validated_beneficiaries: set[str] = set()
        self._operation_ledger = operation_ledger or PostgresVendorAOperationLedger(
            SessionLocal
        )

    def authenticate(self, request: AuthenticationRequest) -> AuthenticationResult:
        """Authenticate using Vendor A's deterministic test credential."""
        self._authenticated = request.credentials.get("api_key") == self._API_KEY
        if self._authenticated:
            return AuthenticationResult(authenticated=True)
        return AuthenticationResult(
            authenticated=False,
            message="Invalid Vendor A credentials",
        )

    def get_capabilities(self) -> VendorCapabilities:
        """Return adapter metadata derived from Vendor A's canonical capability."""
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
        """Describe Vendor A's offering using canonical business terminology."""
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
        """Validate the single deterministic customer accepted by Vendor A."""
        if not self._authenticated:
            return CustomerValidationResult(
                is_valid=False,
                message="Vendor A authentication is required",
            )

        is_valid = (
            request.product_type == self.PRODUCT_TYPE
            and request.network == self.NETWORK
            and request.beneficiary == self._VALID_BENEFICIARY
        )
        if not is_valid:
            return CustomerValidationResult(
                is_valid=False,
                message="Customer is not valid for Vendor A MTN airtime",
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
                message="Vendor A authentication is required",
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
                message="Vendor A supports MTN airtime only",
            )

        return self._operation_ledger.submit(request)

    def query_transaction(
        self, request: TransactionQueryRequest
    ) -> VendorTransactionResult:
        """Query the vendor-owned durable ledger without submitting an operation."""
        return self._operation_ledger.query(request.transaction_id)
