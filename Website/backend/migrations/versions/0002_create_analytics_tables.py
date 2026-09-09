"""create analytics tables

Revision ID: 0002_create_analytics_tables
Revises: 0001_create_users
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_create_analytics_tables"
down_revision = "0001_create_users"
branch_labels = None
depends_on = None

_LANES = [f"l{i:02d}" for i in range(1, 13)]
_LT2 = [f"l{i:02d}_lt2_count" for i in range(1, 13)]


def upgrade() -> None:
    toll_cols = [
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plaza_name", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Text(), nullable=False),
        sa.Column("total_transaction", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vc_3wheeler", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vc_bus_2_axle", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vc_car_jeep", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vc_lcv", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vc_tractor", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vc_truck_4_6_axle", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vc_truck_2_axle", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vc_truck_3_axle", sa.Integer(), server_default="0", nullable=False),
    ]
    toll_cols.extend(
        sa.Column(name, sa.Integer(), server_default="0", nullable=False) for name in _LANES
    )
    toll_cols.extend(
        [
            sa.Column("mop_fastag", sa.Integer(), server_default="0", nullable=False),
            sa.Column("mop_cash", sa.Integer(), server_default="0", nullable=False),
            sa.Column("mop_upi", sa.Integer(), server_default="0", nullable=False),
            sa.Column("mop_exempt", sa.Integer(), server_default="0", nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "plaza_name",
                "date",
                "hour",
                name="uq_toll_analysis_main_plaza_date_hour",
            ),
        ]
    )
    op.create_table("toll_analysis_main", *toll_cols)
    op.create_index(
        op.f("ix_toll_analysis_main_plaza_name"),
        "toll_analysis_main",
        ["plaza_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_toll_analysis_main_date"),
        "toll_analysis_main",
        ["date"],
        unique=False,
    )

    gap_cols = [
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plaza_name", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Text(), nullable=False),
    ]
    gap_cols.extend(sa.Column(name, sa.Float(), nullable=True) for name in _LANES)
    gap_cols.extend(
        sa.Column(name, sa.Integer(), server_default="0", nullable=False) for name in _LT2
    )
    gap_cols.extend(
        [
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "plaza_name",
                "date",
                "hour",
                name="uq_gap_distribution_plaza_date_hour",
            ),
        ]
    )
    op.create_table("gap_distribution_per_lane", *gap_cols)
    op.create_index(
        op.f("ix_gap_distribution_per_lane_plaza_name"),
        "gap_distribution_per_lane",
        ["plaza_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gap_distribution_per_lane_date"),
        "gap_distribution_per_lane",
        ["date"],
        unique=False,
    )

    exempt_cols = [
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plaza_name", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Text(), nullable=False),
    ]
    exempt_cols.extend(
        sa.Column(name, sa.Integer(), server_default="0", nullable=False) for name in _LANES
    )
    exempt_cols.extend(
        [
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "plaza_name",
                "date",
                "hour",
                name="uq_exempt_distribution_plaza_date_hour",
            ),
        ]
    )
    op.create_table("exempt_distribution_per_lane", *exempt_cols)
    op.create_index(
        op.f("ix_exempt_distribution_per_lane_plaza_name"),
        "exempt_distribution_per_lane",
        ["plaza_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_exempt_distribution_per_lane_date"),
        "exempt_distribution_per_lane",
        ["date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_exempt_distribution_per_lane_date"),
        table_name="exempt_distribution_per_lane",
    )
    op.drop_index(
        op.f("ix_exempt_distribution_per_lane_plaza_name"),
        table_name="exempt_distribution_per_lane",
    )
    op.drop_table("exempt_distribution_per_lane")

    op.drop_index(
        op.f("ix_gap_distribution_per_lane_date"),
        table_name="gap_distribution_per_lane",
    )
    op.drop_index(
        op.f("ix_gap_distribution_per_lane_plaza_name"),
        table_name="gap_distribution_per_lane",
    )
    op.drop_table("gap_distribution_per_lane")

    op.drop_index(op.f("ix_toll_analysis_main_date"), table_name="toll_analysis_main")
    op.drop_index(
        op.f("ix_toll_analysis_main_plaza_name"), table_name="toll_analysis_main"
    )
    op.drop_table("toll_analysis_main")
