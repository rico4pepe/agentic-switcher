"""add transaction idempotency and Vendor A operation ledger

Revision ID: 7a9c4d2f1e63
Revises: 1f8de28b9a36
Create Date: 2026-10-06 17:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7a9c4d2f1e63"
down_revision: Union[str, Sequence[str], None] = "1f8de28b9a36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add an optional unique key and the separate simulator-side operation log."""
    op.add_column(
        "transactions",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_transactions_idempotency_key",
        "transactions",
        ["idempotency_key"],
    )
    op.create_table(
        "vendor_a_operations",
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


def downgrade() -> None:
    """Remove simulator ledger and idempotency constraint/column."""
    op.drop_table("vendor_a_operations")
    op.drop_constraint(
        "uq_transactions_idempotency_key",
        "transactions",
        type_="unique",
    )
    op.drop_column("transactions", "idempotency_key")
