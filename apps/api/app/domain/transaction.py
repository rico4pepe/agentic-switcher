"""Transaction domain model and state definitions."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.database import Base


class TransactionState(str, Enum):
    """Lifecycle states for a Switcher transaction."""

    CREATED = "created"
    VALIDATING = "validating"
    VALIDATED = "validated"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    SUCCESS = "success"
    FAILED = "failed"
    UNKNOWN = "unknown"
    INVESTIGATING = "investigating"
    STATUS_RESOLVED = "status_resolved"


class Transaction(Base):
    """Canonical transaction record for the Switcher."""

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_transactions_idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    product_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    network: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    beneficiary: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    state: Mapped[TransactionState] = mapped_column(
        SQLEnum(
            TransactionState,
            native_enum=False,
            length=30,
        ),
        nullable=False,
        default=TransactionState.CREATED,
    )

    vendor_code: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    vendor_reference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    raw_vendor_response: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

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

    def __init__(self, **kwargs) -> None:
        """Initialize a transaction with its initial state."""
        super().__init__(**kwargs)

        if self.state is None:
            self.state = TransactionState.CREATED

    def transition_to(self, target: TransactionState) -> None:
        """Transition the transaction to a valid target state."""
        from apps.api.app.domain.state_machine import TransactionStateMachine

        self.state = TransactionStateMachine.transition(
            self.state,
            target,
        )
