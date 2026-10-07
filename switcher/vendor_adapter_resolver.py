"""Deterministic application-side vendor adapter construction and authentication."""

from apps.api.app.config import Settings
from apps.api.app.database import SessionLocal
from vendors.base.adapter import VendorAdapter
from vendors.base.models import AuthenticationRequest
from vendors.vendor_a import VendorAAdapter
from vendors.vendor_a.operation_ledger import PostgresVendorAOperationLedger
from vendors.vendor_b import VendorBAdapter
from vendors.vendor_b.operation_ledger import PostgresVendorBOperationLedger


class UnsupportedVendorError(ValueError):
    """Raised when an adapter is requested for an unregistered vendor."""


class VendorAuthenticationError(RuntimeError):
    """Raised when application-controlled adapter authentication fails."""


def create_authenticated_adapter(
    vendor_code: str,
    settings: Settings,
) -> VendorAdapter:
    """Construct and authenticate an allow-listed vendor adapter."""
    if vendor_code == VendorAAdapter.VENDOR_CODE:
        adapter = VendorAAdapter(
            PostgresVendorAOperationLedger(SessionLocal),
        )
        result = adapter.authenticate(
            AuthenticationRequest({"api_key": settings.vendor_a_api_key})
        )
    elif vendor_code == VendorBAdapter.VENDOR_CODE:
        adapter = VendorBAdapter(
            PostgresVendorBOperationLedger(SessionLocal),
        )
        result = adapter.authenticate(
            AuthenticationRequest({"api_key": settings.vendor_b_api_key})
        )
    else:
        raise UnsupportedVendorError(f"Unsupported vendor: {vendor_code}")

    if not result.authenticated:
        raise VendorAuthenticationError(
            f"Authentication failed for vendor: {vendor_code}"
        )

    return adapter
