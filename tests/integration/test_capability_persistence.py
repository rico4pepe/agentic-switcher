"""PostgreSQL integration tests for canonical capability persistence."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.app.database import SessionLocal, engine
from apps.api.app.persistence.capability import (
    CapabilityRecord,
    capability_to_record,
    record_to_capability,
)
from capabilities.domain import Capability, CapabilityOperation, WorkflowStep


@pytest.fixture
def postgres_session() -> Iterator[Session]:
    """Provide a session connected to the configured PostgreSQL database."""
    assert engine.dialect.name == "postgresql"
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def capability_ids(postgres_session: Session) -> Iterator[list[UUID]]:
    """Remove only capability records created by the integration tests."""
    record_ids: list[UUID] = []
    try:
        yield record_ids
    finally:
        postgres_session.rollback()
        if record_ids:
            postgres_session.execute(
                delete(CapabilityRecord).where(CapabilityRecord.id.in_(record_ids))
            )
            postgres_session.commit()


def test_capability_persists_and_reloads_with_product_attributes(
    postgres_session: Session,
    capability_ids: list[UUID],
):
    capability = Capability(
        vendor_code="test_vendor",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        supported_operations=frozenset(CapabilityOperation),
        workflow=(WorkflowStep(CapabilityOperation.EXECUTE_TRANSACTION),),
        product_attributes={"channel": "integration-test"},
    )
    record = capability_to_record(capability)
    postgres_session.add(record)
    postgres_session.commit()
    capability_ids.append(record.id)
    record_id = record.id
    postgres_session.expunge_all()

    reloaded = postgres_session.get(CapabilityRecord, record_id)

    assert reloaded is not None
    reloaded_capability = record_to_capability(reloaded)
    assert reloaded_capability == capability
    assert reloaded.product_attributes == {"channel": "integration-test"}


def test_supported_operations_and_workflow_order_survive_persistence(
    postgres_session: Session,
    capability_ids: list[UUID],
):
    capability = Capability(
        vendor_code="workflow_test_vendor",
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        supported_operations=frozenset(CapabilityOperation),
        workflow=(
            WorkflowStep(CapabilityOperation.AUTHENTICATE, required=True),
            WorkflowStep(CapabilityOperation.VALIDATE_CUSTOMER, required=False),
            WorkflowStep(CapabilityOperation.EXECUTE_TRANSACTION, required=True),
            WorkflowStep(CapabilityOperation.QUERY_TRANSACTION, required=True),
        ),
    )
    record = capability_to_record(capability)
    postgres_session.add(record)
    postgres_session.commit()
    capability_ids.append(record.id)
    record_id = record.id
    postgres_session.expunge_all()

    reloaded = postgres_session.get(CapabilityRecord, record_id)
    assert reloaded is not None
    reloaded_capability = record_to_capability(reloaded)

    assert reloaded_capability.supported_operations == frozenset(CapabilityOperation)
    assert [step.operation for step in reloaded_capability.workflow] == [
        CapabilityOperation.AUTHENTICATE,
        CapabilityOperation.VALIDATE_CUSTOMER,
        CapabilityOperation.EXECUTE_TRANSACTION,
        CapabilityOperation.QUERY_TRANSACTION,
    ]
    assert [step.required for step in reloaded_capability.workflow] == [
        True,
        False,
        True,
        True,
    ]


def test_seeded_vendor_a_mtn_airtime_capability_is_represented():
    session = SessionLocal()
    try:
        record = session.scalar(
            select(CapabilityRecord).where(
                CapabilityRecord.vendor_code == "vendor_a",
                CapabilityRecord.service_type == "airtime",
                CapabilityRecord.product_type == "airtime",
                CapabilityRecord.network == "MTN",
            )
        )
        assert record is not None
        capability = record_to_capability(record)
        assert capability.vendor_code == "vendor_a"
        assert capability.workflow == (
            WorkflowStep(CapabilityOperation.AUTHENTICATE, required=True),
            WorkflowStep(CapabilityOperation.VALIDATE_CUSTOMER, required=True),
            WorkflowStep(CapabilityOperation.EXECUTE_TRANSACTION, required=True),
            WorkflowStep(CapabilityOperation.QUERY_TRANSACTION, required=True),
        )
    finally:
        session.close()
