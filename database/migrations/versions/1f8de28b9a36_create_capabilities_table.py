"""create capabilities table

Revision ID: 1f8de28b9a36
Revises: 5c1764681123
Create Date: 2026-10-03 04:00:00.000000
"""

from datetime import UTC, datetime
from typing import Sequence, Union
from uuid import UUID

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "1f8de28b9a36"
down_revision: Union[str, Sequence[str], None] = "5c1764681123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create canonical capability storage and seed Vendor A airtime."""
    op.create_table(
        "capabilities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("vendor_code", sa.String(length=50), nullable=False),
        sa.Column("service_type", sa.String(length=50), nullable=False),
        sa.Column("product_type", sa.String(length=50), nullable=False),
        sa.Column("network", sa.String(length=50), nullable=True),
        sa.Column("supported_operations", postgresql.JSONB(), nullable=False),
        sa.Column("workflow", postgresql.JSONB(), nullable=False),
        sa.Column("product_attributes", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "vendor_code",
            "service_type",
            "product_type",
            "network",
            name="uq_capabilities_identity",
        ),
    )
    capabilities = sa.table(
        "capabilities",
        sa.column("id", sa.UUID()),
        sa.column("vendor_code", sa.String()),
        sa.column("service_type", sa.String()),
        sa.column("product_type", sa.String()),
        sa.column("network", sa.String()),
        sa.column("supported_operations", postgresql.JSONB()),
        sa.column("workflow", postgresql.JSONB()),
        sa.column("product_attributes", postgresql.JSONB()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        capabilities,
        [
            {
                "id": UUID("8d721bc8-a2be-47db-9b5a-55cd2daee9b0"),
                "vendor_code": "vendor_a",
                "service_type": "airtime",
                "product_type": "airtime",
                "network": "MTN",
                "supported_operations": [
                    "authenticate",
                    "validate_customer",
                    "execute_transaction",
                    "query_transaction",
                ],
                "workflow": [
                    {"operation": "authenticate", "required": True},
                    {"operation": "validate_customer", "required": True},
                    {"operation": "execute_transaction", "required": True},
                    {"operation": "query_transaction", "required": True},
                ],
                "product_attributes": {},
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    """Remove canonical capability storage and its seed record."""
    op.drop_table("capabilities")
