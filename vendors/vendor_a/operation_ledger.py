"""Durable operation state owned by the Vendor A simulator."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from apps.api.app.database import Base
from vendors.base.models import (
    TransactionExecutionRequest,
    VendorTransactionResult,
    VendorTransactionStatus,
)


class VendorAOperationRecord(Base):
    """Vendor-owned status record, separate from the canonical transaction."""

    __tablename__ = "vendor_a_operations"

    transaction_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    vendor_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_response: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class VendorAOperationLedger(Protocol):
    """Storage contract for operation results reported by simulated Vendor A."""

    def submit(
        self, request: TransactionExecutionRequest
    ) -> VendorTransactionResult: ...

    def query(self, transaction_id: UUID) -> VendorTransactionResult: ...


def _result(
    *,
    transaction_id: UUID,
    status: VendorTransactionStatus,
    message: str | None = None,
) -> VendorTransactionResult:
    return VendorTransactionResult(
        status=status,
        vendor_reference=f"vendor_a-{transaction_id}",
        message=message,
        raw_response={"status": status.value},
    )


def _record_result(record: VendorAOperationRecord) -> VendorTransactionResult:
    return VendorTransactionResult(
        status=VendorTransactionStatus(record.status),
        vendor_reference=record.vendor_reference,
        message=record.message,
        raw_response=dict(record.raw_response),
    )


class InMemoryVendorAOperationLedger:
    """Instance-local ledger for isolated adapter unit tests."""

    def __init__(
        self,
        submission_status: VendorTransactionStatus = VendorTransactionStatus.SUCCESS,
    ) -> None:
        self._submission_status = submission_status
        self._operations: dict[UUID, VendorTransactionResult] = {}

    def submit(
        self, request: TransactionExecutionRequest
    ) -> VendorTransactionResult:
        return self._operations.setdefault(
            request.transaction_id,
            _result(
                transaction_id=request.transaction_id,
                status=self._submission_status,
                message=(
                    "Vendor A transaction failed"
                    if self._submission_status == VendorTransactionStatus.FAILED
                    else None
                ),
            ),
        )

    def query(self, transaction_id: UUID) -> VendorTransactionResult:
        return self._operations.get(
            transaction_id,
            _result(
                transaction_id=transaction_id,
                status=VendorTransactionStatus.UNKNOWN,
                message="Vendor A operation was not found",
            ),
        )


class PostgresVendorAOperationLedger:
    """Persist simulator-side status independently in the shared PostgreSQL DB."""

    def __init__(
        self,
        session_factory: sessionmaker,
        submission_status: VendorTransactionStatus = VendorTransactionStatus.SUCCESS,
    ) -> None:
        self._session_factory = session_factory
        self._submission_status = submission_status

    def submit(
        self, request: TransactionExecutionRequest
    ) -> VendorTransactionResult:
        status = self._submission_status
        candidate = VendorAOperationRecord(
            transaction_id=request.transaction_id,
            status=status.value,
            vendor_reference=f"vendor_a-{request.transaction_id}",
            message=(
                "Vendor A transaction failed"
                if status == VendorTransactionStatus.FAILED
                else None
            ),
            raw_response={"status": status.value},
        )
        with self._session_factory() as session:
            existing = session.get(
                VendorAOperationRecord,
                request.transaction_id,
            )
            if existing is not None:
                return _record_result(existing)
            session.add(candidate)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.get(
                    VendorAOperationRecord,
                    request.transaction_id,
                )
                if existing is None:
                    raise
                return _record_result(existing)
            return _record_result(candidate)

    def query(self, transaction_id: UUID) -> VendorTransactionResult:
        with self._session_factory() as session:
            record = session.get(VendorAOperationRecord, transaction_id)
            if record is None:
                return _result(
                    transaction_id=transaction_id,
                    status=VendorTransactionStatus.UNKNOWN,
                    message="Vendor A operation was not found",
                )
            return _record_result(record)
