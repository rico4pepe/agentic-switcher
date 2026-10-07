"""Tests for deterministic vendor adapter construction and authentication."""

import pytest

from apps.api.app.config import Settings
from switcher.vendor_adapter_resolver import (
    UnsupportedVendorError,
    VendorAuthenticationError,
    create_authenticated_adapter,
)
from vendors.base.adapter import VendorAdapter
from vendors.vendor_a import VendorAAdapter
from vendors.vendor_b import VendorBAdapter


def test_vendor_a_resolves_to_authenticated_adapter():
    settings = Settings(
        database_url="sqlite://",
        vendor_a_api_key="vendor_a_test_key",
    )

    adapter = create_authenticated_adapter("vendor_a", settings)

    assert isinstance(adapter, VendorAAdapter)
    assert isinstance(adapter, VendorAdapter)


def test_vendor_b_resolves_to_authenticated_adapter():
    settings = Settings(
        database_url="sqlite://",
        vendor_b_api_key="vendor_b_test_key",
    )

    adapter = create_authenticated_adapter("vendor_b", settings)

    assert isinstance(adapter, VendorBAdapter)
    assert isinstance(adapter, VendorAdapter)


def test_unknown_vendor_is_rejected():
    settings = Settings(database_url="sqlite://")

    with pytest.raises(UnsupportedVendorError, match="Unsupported vendor: missing"):
        create_authenticated_adapter("missing", settings)


def test_vendor_authentication_failure_is_rejected():
    settings = Settings(
        database_url="sqlite://",
        vendor_a_api_key="invalid-test-key",
    )

    with pytest.raises(
        VendorAuthenticationError,
        match="Authentication failed for vendor: vendor_a",
    ):
        create_authenticated_adapter("vendor_a", settings)
