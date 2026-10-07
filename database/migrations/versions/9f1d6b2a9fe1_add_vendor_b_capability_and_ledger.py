"""add Vendor B capability and operation ledger

Revision ID: 9f1d6b2a9fe1
Revises: 7a9c4d2f1e63
Create Date: 2026-10-07 00:00:00.000000
"""

from datetime import UTC, datetime
from typing import Sequence, Union
from uuid import UUID

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9f1d6b2a9fe1"
down_revision: Union[str, Sequence[str], None] = "7a9c4d2f1e63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the Vendor B ledger and add its canonical capability."""
    op.create_table(
        "vendor_b_operations",
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("vendor_reference", sa.String(length=100), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.Column(
            "raw_response",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("transaction_id"),
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
                "id": UUID("2a884e68-3774-4ae8-91b1-0a2d8d4d4f07"),
                "vendor_code": "vendor_b",
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
    """Remove Vendor B ledger and capability record."""
    op.drop_table("vendor_b_operations")
    op.execute(
        "DELETE FROM capabilities WHERE vendor_code = 'vendor_b'"
    )
