"""PostgreSQL integration tests for deterministic capability lookup."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from apps.api.app.database import SessionLocal, engine
from apps.api.app.persistence.capability import CapabilityRecord, capability_to_record
from capabilities.domain import Capability, CapabilityOperation, WorkflowStep
from capabilities.registry import CapabilityRegistry


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
    """Remove only records created by registry integration tests."""
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


def make_capability(vendor_code: str) -> Capability:
    """Build a canonical MTN airtime capability for a test vendor."""
    return Capability(
        vendor_code=vendor_code,
        service_type="airtime",
        product_type="airtime",
        network="MTN",
        supported_operations=frozenset(CapabilityOperation),
        workflow=(WorkflowStep(CapabilityOperation.EXECUTE_TRANSACTION),),
    )


def persist(
    session: Session,
    capability_ids: list[UUID],
    capability: Capability,
) -> None:
    """Persist and track a capability for isolated test cleanup."""
    record = capability_to_record(capability)
    session.add(record)
    session.commit()
    capability_ids.append(record.id)


def test_vendor_a_mtn_airtime_is_found_through_registry(postgres_session: Session):
    matches = CapabilityRegistry(postgres_session).find(
        service_type="airtime",
        product_type="airtime",
        network="MTN",
    )

    assert any(capability.vendor_code == "vendor_a" for capability in matches)


def test_registry_returns_canonical_capability_objects(postgres_session: Session):
    matches = CapabilityRegistry(postgres_session).find(
        service_type="airtime",
        product_type="airtime",
        network="MTN",
    )

    assert matches
    assert all(isinstance(capability, Capability) for capability in matches)


def test_registry_matches_exact_canonical_business_fields(postgres_session: Session):
    registry = CapabilityRegistry(postgres_session)

    matches = registry.find(
        service_type="airtime",
        product_type="airtime",
        network="MTN",
    )
    non_matches = registry.find(
        service_type="airtime",
        product_type="airtime",
        network="GLO",
    )

    assert matches
    assert non_matches == ()


def test_registry_returns_multiple_matches_without_ranking(
    postgres_session: Session,
    capability_ids: list[UUID],
):
    persist(postgres_session, capability_ids, make_capability("test_vendor_b"))
    persist(postgres_session, capability_ids, make_capability("test_vendor_c"))

    matches = CapabilityRegistry(postgres_session).find(
        service_type="airtime",
        product_type="airtime",
        network="MTN",
    )

    assert {capability.vendor_code for capability in matches} >= {
        "vendor_a",
        "test_vendor_b",
        "test_vendor_c",
    }
    assert [capability.vendor_code for capability in matches] == sorted(
        capability.vendor_code for capability in matches
    )


def test_registry_lookup_does_not_require_vendor_product_code(postgres_session: Session):
    matches = CapabilityRegistry(postgres_session).find(
        service_type="airtime",
        product_type="airtime",
        network="MTN",
    )

    vendor_a = next(
        capability for capability in matches if capability.vendor_code == "vendor_a"
    )
    assert vendor_a.product_type == "airtime"
