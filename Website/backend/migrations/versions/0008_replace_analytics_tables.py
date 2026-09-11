"""replace analytics fact tables with named distribution tables

Revision ID: 0008_replace_analytics_tables
Revises: 0007_analytics_plaza_identifier
Create Date: 2026-09-11 12:50:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0008_replace_analytics_tables"
down_revision = "0007_analytics_plaza_identifier"
branch_labels = None
depends_on = None


def _drop_table_if_exists(table_name: str) -> None:
    op.execute(sa.text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))


def upgrade():
    # Remove legacy analytics tables (including any plaza_identifier columns from 0007).
    for table_name in (
        "toll_analysis_main",
        "exempt_distribution_per_lane",
        "gap_distribution_per_lane",
    ):
        _drop_table_if_exists(table_name)

    op.create_table(
        "mop_distribution_per_class",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plaza_identifier", sa.Text(), nullable=False),
        sa.Column("plaza_name", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Text(), nullable=False),
        sa.Column("vehicle_class", sa.Text(), nullable=False),
        sa.Column("mop", sa.Text(), nullable=False),
        sa.Column("txn_count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plaza_identifier",
            "date",
            "hour",
            "vehicle_class",
            "mop",
            name="uq_mop_distribution_per_class",
        ),
    )
    op.create_index(
        op.f("ix_mop_distribution_per_class_plaza_identifier"),
        "mop_distribution_per_class",
        ["plaza_identifier"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mop_distribution_per_class_plaza_name"),
        "mop_distribution_per_class",
        ["plaza_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mop_distribution_per_class_date"),
        "mop_distribution_per_class",
        ["date"],
        unique=False,
    )

    op.create_table(
        "class_distribution_per_lane",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plaza_identifier", sa.Text(), nullable=False),
        sa.Column("plaza_name", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Text(), nullable=False),
        sa.Column("lane", sa.Text(), nullable=False),
        sa.Column("vehicle_class", sa.Text(), nullable=False),
        sa.Column("txn_count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plaza_identifier",
            "date",
            "hour",
            "lane",
            "vehicle_class",
            name="uq_class_distribution_per_lane",
        ),
    )
    op.create_index(
        op.f("ix_class_distribution_per_lane_plaza_identifier"),
        "class_distribution_per_lane",
        ["plaza_identifier"],
        unique=False,
    )
    op.create_index(
        op.f("ix_class_distribution_per_lane_plaza_name"),
        "class_distribution_per_lane",
        ["plaza_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_class_distribution_per_lane_date"),
        "class_distribution_per_lane",
        ["date"],
        unique=False,
    )

    op.create_table(
        "mop_distribution_per_lane",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plaza_identifier", sa.Text(), nullable=False),
        sa.Column("plaza_name", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Text(), nullable=False),
        sa.Column("lane", sa.Text(), nullable=False),
        sa.Column("mop", sa.Text(), nullable=False),
        sa.Column("txn_count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plaza_identifier",
            "date",
            "hour",
            "lane",
            "mop",
            name="uq_mop_distribution_per_lane",
        ),
    )
    op.create_index(
        op.f("ix_mop_distribution_per_lane_plaza_identifier"),
        "mop_distribution_per_lane",
        ["plaza_identifier"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mop_distribution_per_lane_plaza_name"),
        "mop_distribution_per_lane",
        ["plaza_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mop_distribution_per_lane_date"),
        "mop_distribution_per_lane",
        ["date"],
        unique=False,
    )

    gap_cols = [
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plaza_identifier", sa.Text(), nullable=False),
        sa.Column("plaza_name", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Text(), nullable=False),
    ]
    for i in range(1, 13):
        gap_cols.append(sa.Column(f"l{i:02d}", sa.Float(), nullable=True))
    for i in range(1, 13):
        gap_cols.append(
            sa.Column(
                f"l{i:02d}_lt2_count",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
    gap_cols.append(sa.PrimaryKeyConstraint("id"))
    gap_cols.append(
        sa.UniqueConstraint(
            "plaza_identifier",
            "date",
            "hour",
            name="uq_gap_distribution_per_lane",
        )
    )
    op.create_table("gap_distribution_per_lane", *gap_cols)
    op.create_index(
        op.f("ix_gap_distribution_per_lane_plaza_identifier"),
        "gap_distribution_per_lane",
        ["plaza_identifier"],
        unique=False,
    )
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


def downgrade():
    for table_name in (
        "gap_distribution_per_lane",
        "mop_distribution_per_lane",
        "class_distribution_per_lane",
        "mop_distribution_per_class",
    ):
        _drop_table_if_exists(table_name)
