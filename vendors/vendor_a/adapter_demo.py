"""Demo-aware Vendor A adapter integrating the scenario timeout hook.

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
from vendors.vendor_a.adapter import VendorAAdapter
from vendors.vendor_a.operation_ledger import (
    PostgresVendorAOperationLedger,
    VendorAOperationLedger,
)


class DemoAwareVendorAAdapter(VendorAAdapter):
    """Vendor A adapter that honors the active demo scenario's timeout condition."""

    def __init__(self, operation_ledger: VendorAOperationLedger | None = None) -> None:
        super().__init__(
            operation_ledger or PostgresVendorAOperationLedger(SessionLocal)
        )

    def execute_transaction(
        self, request: TransactionExecutionRequest
    ) -> VendorTransactionResult:
        if get_demo_scenario_config().vendor_simulation.vendor_a_timeout:
            raise TimeoutError("simulated response timeout")
        return super().execute_transaction(request)
