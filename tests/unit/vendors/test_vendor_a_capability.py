"""Tests for Vendor A's canonical capability declaration."""

from apps.api.app.persistence.capability import capability_to_record, record_to_capability
from capabilities.domain import Capability, CapabilityOperation, WorkflowStep
from vendors.vendor_a import VendorAAdapter


def test_vendor_a_exposes_canonical_mtn_airtime_capability():
    capability = VendorAAdapter().get_canonical_capability()

    assert isinstance(capability, Capability)
    assert capability.vendor_code == "vendor_a"
    assert capability.service_type == "airtime"
    assert capability.product_type == "airtime"
    assert capability.network == "MTN"


def test_vendor_a_canonical_capability_contains_expected_operations():
    capability = VendorAAdapter().get_canonical_capability()

    assert capability.supported_operations == frozenset(CapabilityOperation)


def test_vendor_a_canonical_capability_preserves_workflow_order():
    capability = VendorAAdapter().get_canonical_capability()

    assert [step.operation for step in capability.workflow] == [
        CapabilityOperation.AUTHENTICATE,
        CapabilityOperation.VALIDATE_CUSTOMER,
        CapabilityOperation.EXECUTE_TRANSACTION,
        CapabilityOperation.QUERY_TRANSACTION,
    ]


def test_vendor_a_canonical_validation_step_is_required():
    capability = VendorAAdapter().get_canonical_capability()

    assert capability.workflow[1] == WorkflowStep(
        CapabilityOperation.VALIDATE_CUSTOMER,
        required=True,
    )


def test_vendor_a_canonical_capability_uses_existing_persistence_mapper():
    capability = VendorAAdapter().get_canonical_capability()

    assert record_to_capability(capability_to_record(capability)) == capability
