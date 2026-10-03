"""Tests for canonical capability and workflow domain models."""

from dataclasses import fields

import pytest

from capabilities.domain import Capability, CapabilityOperation, WorkflowStep


def vendor_a_airtime_capability() -> Capability:
    """Represent Vendor A's MTN airtime offering in canonical business terms."""
    return Capability(
        vendor_code="vendor_a",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        supported_operations=frozenset(CapabilityOperation),
        workflow=(
            WorkflowStep(CapabilityOperation.AUTHENTICATE),
            WorkflowStep(CapabilityOperation.VALIDATE_CUSTOMER, required=True),
            WorkflowStep(CapabilityOperation.EXECUTE_TRANSACTION),
            WorkflowStep(CapabilityOperation.QUERY_TRANSACTION),
        ),
    )


def test_vendor_a_airtime_capability_can_be_represented():
    capability = vendor_a_airtime_capability()

    assert capability.vendor_code == "vendor_a"
    assert capability.service_type == "airtime"
    assert capability.product_type == "airtime"
    assert capability.network == "MTN"


def test_supported_operations_are_typed():
    capability = vendor_a_airtime_capability()

    assert capability.supported_operations == frozenset(CapabilityOperation)
    assert all(
        isinstance(operation, CapabilityOperation)
        for operation in capability.supported_operations
    )


def test_workflow_ordering_is_preserved():
    capability = vendor_a_airtime_capability()

    assert [step.operation for step in capability.workflow] == [
        CapabilityOperation.AUTHENTICATE,
        CapabilityOperation.VALIDATE_CUSTOMER,
        CapabilityOperation.EXECUTE_TRANSACTION,
        CapabilityOperation.QUERY_TRANSACTION,
    ]


def test_required_workflow_steps_are_represented():
    capability = vendor_a_airtime_capability()

    validation_step = capability.workflow[1]

    assert validation_step.operation == CapabilityOperation.VALIDATE_CUSTOMER
    assert validation_step.required


def test_empty_workflow_is_rejected():
    with pytest.raises(ValueError, match="workflow must contain at least one step"):
        Capability(
            vendor_code="vendor_a",
            service_type="airtime",
            product_type="airtime",
            network="MTN",
            supported_operations=frozenset(CapabilityOperation),
            workflow=(),
        )


def test_canonical_capability_has_no_vendor_specific_product_code():
    field_names = {field.name for field in fields(Capability)}

    assert "vendor_product_code" not in field_names
