"""Deterministic lookup of persisted canonical capabilities."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.persistence.capability import CapabilityRecord, record_to_capability
from capabilities.domain import Capability


class CapabilityRegistry:
    """Read canonical capabilities matching an exact business identity."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find(
        self,
        *,
        service_type: str,
        product_type: str,
        network: str | None,
    ) -> tuple[Capability, ...]:
        """Return all exact canonical matches without vendor selection or ranking."""
        statement = (
            select(CapabilityRecord)
            .where(
                CapabilityRecord.service_type == service_type,
                CapabilityRecord.product_type == product_type,
                CapabilityRecord.network == network,
            )
            .order_by(CapabilityRecord.vendor_code, CapabilityRecord.id)
        )
        records = self._session.scalars(statement).all()
        return tuple(record_to_capability(record) for record in records)
