"""add composite (plaza_identifier, date) indexes on analytics fact tables

Revision ID: 0011_plaza_date_idx
Revises: 0010_plaza_calendar_events
Create Date: 2026-09-16 14:50:00.000000

"""

from __future__ import annotations

from alembic import op


revision = "0011_plaza_date_idx"
down_revision = "0010_plaza_calendar_events"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_mop_class_plaza_date", "mop_distribution_per_class"),
    ("ix_class_lane_plaza_date", "class_distribution_per_lane"),
    ("ix_mop_lane_plaza_date", "mop_distribution_per_lane"),
    ("ix_gap_lane_plaza_date", "gap_distribution_per_lane"),
)


def upgrade():
    for index_name, table_name in INDEXES:
        op.create_index(
            index_name,
            table_name,
            ["plaza_identifier", "date"],
            unique=False,
        )


def downgrade():
    for index_name, table_name in reversed(INDEXES):
        op.drop_index(index_name, table_name=table_name)
