"""create plaza calendar events table

Revision ID: 0010_plaza_calendar_events
Revises: 0009_audit_exceptions
Create Date: 2026-09-15 22:50:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_plaza_calendar_events"
down_revision = "0009_audit_exceptions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plaza_calendar_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plaza_identifier", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "end_date >= start_date",
            name="ck_plaza_calendar_events_date_range",
        ),
        sa.ForeignKeyConstraint(
            ["plaza_identifier"],
            ["plazas.plaza_identifier"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_plaza_calendar_events_plaza_identifier"),
        "plaza_calendar_events",
        ["plaza_identifier"],
        unique=False,
    )
    op.create_index(
        "ix_plaza_calendar_events_plaza_start",
        "plaza_calendar_events",
        ["plaza_identifier", "start_date"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_plaza_calendar_events_plaza_start",
        table_name="plaza_calendar_events",
    )
    op.drop_index(
        op.f("ix_plaza_calendar_events_plaza_identifier"),
        table_name="plaza_calendar_events",
    )
    op.drop_table("plaza_calendar_events")
