"""Deterministic application-side vendor adapter construction and authentication."""

from apps.api.app.config import Settings
from vendors.base.adapter import VendorAdapter
from vendors.base.models import AuthenticationRequest
from vendors.vendor_a import VendorAAdapter


class UnsupportedVendorError(ValueError):
    """Raised when an adapter is requested for an unregistered vendor."""


class VendorAuthenticationError(RuntimeError):
    """Raised when application-controlled adapter authentication fails."""


def create_authenticated_adapter(
    vendor_code: str,
    settings: Settings,
) -> VendorAdapter:
    """Construct and authenticate an allow-listed vendor adapter."""
    if vendor_code != VendorAAdapter.VENDOR_CODE:
        raise UnsupportedVendorError(f"Unsupported vendor: {vendor_code}")

    adapter = VendorAAdapter()
    result = adapter.authenticate(
        AuthenticationRequest({"api_key": settings.vendor_a_api_key})
    )
    if not result.authenticated:
        raise VendorAuthenticationError(
            f"Authentication failed for vendor: {vendor_code}"
        )

    return adapter
