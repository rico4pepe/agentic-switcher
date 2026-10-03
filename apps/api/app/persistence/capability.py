"""SQLAlchemy persistence model and mapping for canonical capabilities."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.database import Base
from capabilities.domain import Capability, CapabilityOperation, WorkflowStep


class CapabilityRecord(Base):
    """Database representation of a canonical capability."""

    __tablename__ = "capabilities"
    __table_args__ = (
        UniqueConstraint(
            "vendor_code",
            "service_type",
            "product_type",
            "network",
            name="uq_capabilities_identity",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    vendor_code: Mapped[str] = mapped_column(String(50), nullable=False)
    service_type: Mapped[str] = mapped_column(String(50), nullable=False)
    product_type: Mapped[str] = mapped_column(String(50), nullable=False)
    network: Mapped[str | None] = mapped_column(String(50), nullable=True)
    supported_operations: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    workflow: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    product_attributes: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


def capability_to_record(capability: Capability) -> CapabilityRecord:
    """Convert a pure canonical capability to its SQLAlchemy record."""
    return CapabilityRecord(
        vendor_code=capability.vendor_code,
        service_type=capability.service_type,
        product_type=capability.product_type,
        network=capability.network,
        supported_operations=sorted(
            operation.value for operation in capability.supported_operations
        ),
        workflow=[
            {"operation": step.operation.value, "required": step.required}
            for step in capability.workflow
        ],
        product_attributes=dict(capability.product_attributes),
    )


def record_to_capability(record: CapabilityRecord) -> Capability:
    """Convert a SQLAlchemy record back to the pure canonical capability."""
    return Capability(
        vendor_code=record.vendor_code,
        service_type=record.service_type,
        product_type=record.product_type,
        network=record.network,
        supported_operations=frozenset(
            CapabilityOperation(operation) for operation in record.supported_operations
        ),
        workflow=tuple(
            WorkflowStep(
                operation=CapabilityOperation(str(step["operation"])),
                required=bool(step["required"]),
            )
            for step in record.workflow
        ),
        product_attributes=dict(record.product_attributes),
    )
