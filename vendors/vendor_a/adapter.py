"""Deterministic simulated implementation of Vendor A."""

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


class VendorAAdapter(VendorAdapter):
    """In-memory Vendor A simulator for MTN airtime transactions.

    The simulator keeps session and submitted-transaction state per adapter
    instance so its workflow can be exercised without network or database I/O.
    """

    VENDOR_CODE = "vendor_a"
    PRODUCT_TYPE = "airtime"
    NETWORK = "MTN"
    _API_KEY = "vendor_a_test_key"
    _VALID_BENEFICIARY = "08030000000"
    _CUSTOMER_NAME = "Ada Okafor"

    def __init__(self) -> None:
        self._authenticated = False
        self._validated_beneficiaries: set[str] = set()
        self._transactions: dict[str, VendorTransactionResult] = {}

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
        """Return Vendor A's MTN airtime workflow capabilities."""
        return VendorCapabilities(
            vendor_code=self.VENDOR_CODE,
            supported_product_types=frozenset({self.PRODUCT_TYPE}),
            supported_operations=frozenset(VendorOperation),
            requires_customer_validation=True,
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

        vendor_reference = f"vendor_a-{request.transaction_id}"
        result = VendorTransactionResult(
            status=VendorTransactionStatus.SUCCESS,
            vendor_reference=vendor_reference,
        )
        self._transactions[vendor_reference] = result
        return result

    def query_transaction(
        self, request: TransactionQueryRequest
    ) -> VendorTransactionResult:
        """Return the recorded Vendor A result or a deterministic unknown result."""
        return self._transactions.get(
            request.vendor_reference,
            VendorTransactionResult(
                status=VendorTransactionStatus.UNKNOWN,
                vendor_reference=request.vendor_reference,
                message="Vendor A transaction reference was not found",
            ),
        )
