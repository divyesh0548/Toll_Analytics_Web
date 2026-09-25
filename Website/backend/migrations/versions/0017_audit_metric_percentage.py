"""store a percentage on audit_exception_metrics

Revision ID: 0017_audit_metric_percentage
Revises: 0016_audit_e10_segments
Create Date: 2026-09-25 15:55:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0017_audit_metric_percentage"
down_revision = "0016_audit_e10_segments"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "audit_exception_metrics",
        sa.Column("percentage", sa.Numeric(8, 2), nullable=True),
    )
    op.alter_column(
        "audit_exception_metrics",
        "total_amount",
        existing_type=sa.Numeric(18, 2),
        nullable=True,
    )
    op.alter_column(
        "audit_exception_metrics",
        "total_count",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade():
    op.execute(
        sa.text(
            "UPDATE audit_exception_metrics SET total_amount = 0 WHERE total_amount IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE audit_exception_metrics SET total_count = 0 WHERE total_count IS NULL"
        )
    )
    op.alter_column(
        "audit_exception_metrics",
        "total_count",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "audit_exception_metrics",
        "total_amount",
        existing_type=sa.Numeric(18, 2),
        nullable=False,
    )
    op.drop_column("audit_exception_metrics", "percentage")
