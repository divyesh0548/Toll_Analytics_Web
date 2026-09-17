"""create plaza_daily_revenue table

Revision ID: 0013_plaza_daily_revenue
Revises: 0012_audit_e13_e14
Create Date: 2026-09-16 19:20:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0013_plaza_daily_revenue"
down_revision = "0012_audit_e13_e14"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plaza_daily_revenue",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plaza_identifier", sa.String(length=36), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("revenue", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["plaza_identifier"],
            ["plazas.plaza_identifier"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plaza_identifier",
            "date",
            name="uq_plaza_daily_revenue_plaza_date",
        ),
    )
    op.create_index(
        op.f("ix_plaza_daily_revenue_plaza_identifier"),
        "plaza_daily_revenue",
        ["plaza_identifier"],
        unique=False,
    )
    op.create_index(
        op.f("ix_plaza_daily_revenue_date"),
        "plaza_daily_revenue",
        ["date"],
        unique=False,
    )
    op.create_index(
        "ix_plaza_daily_revenue_plaza_date",
        "plaza_daily_revenue",
        ["plaza_identifier", "date"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_plaza_daily_revenue_plaza_date", table_name="plaza_daily_revenue")
    op.drop_index(op.f("ix_plaza_daily_revenue_date"), table_name="plaza_daily_revenue")
    op.drop_index(
        op.f("ix_plaza_daily_revenue_plaza_identifier"),
        table_name="plaza_daily_revenue",
    )
    op.drop_table("plaza_daily_revenue")
