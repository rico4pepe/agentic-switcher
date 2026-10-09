"""Demo-aware Vendor B adapter integrating the scenario timeout hook.

The timeout behavior is implemented at the vendor simulation boundary by
raising during submission, exactly as a real uncertain submission would. The
existing transaction state machine then classifies the operation as UNKNOWN.
"""

from apps.api.app.database import SessionLocal
from switcher.demo.scenarios import get_demo_scenario_config
from vendors.base.models import (
    TransactionExecutionRequest,
    VendorTransactionResult,
)
from vendors.vendor_b.adapter import VendorBAdapter
from vendors.vendor_b.operation_ledger import (
    PostgresVendorBOperationLedger,
    VendorBOperationLedger,
)


class DemoAwareVendorBAdapter(VendorBAdapter):
    """Vendor B adapter that honors the active demo scenario's timeout condition."""

    def __init__(self, operation_ledger: VendorBOperationLedger | None = None) -> None:
        super().__init__(
            operation_ledger or PostgresVendorBOperationLedger(SessionLocal)
        )

    def execute_transaction(
        self, request: TransactionExecutionRequest
    ) -> VendorTransactionResult:
        if get_demo_scenario_config().vendor_simulation.vendor_b_timeout:
            raise TimeoutError("simulated response timeout")
        return super().execute_transaction(request)
