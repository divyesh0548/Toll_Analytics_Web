"""add plaza_identifier to analytics tables

Revision ID: 0007_analytics_plaza_identifier
Revises: 0d481b224a34
Create Date: 2026-09-11 12:20:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0007_analytics_plaza_identifier"
down_revision = "0d481b224a34"
branch_labels = None
depends_on = None

TABLES = (
    "toll_analysis_main",
    "gap_distribution_per_lane",
    "exempt_distribution_per_lane",
)

OLD_UNIQUES = {
    "toll_analysis_main": "uq_toll_analysis_main_plaza_date_hour",
    "gap_distribution_per_lane": "uq_gap_distribution_plaza_date_hour",
    "exempt_distribution_per_lane": "uq_exempt_distribution_plaza_date_hour",
}


def upgrade():
    for table_name in TABLES:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(sa.Column("plaza_identifier", sa.Text(), nullable=True))
            batch_op.create_index(
                batch_op.f(f"ix_{table_name}_plaza_identifier"),
                ["plaza_identifier"],
                unique=False,
            )
            batch_op.drop_constraint(OLD_UNIQUES[table_name], type_="unique")
            batch_op.create_unique_constraint(
                OLD_UNIQUES[table_name],
                ["plaza_identifier", "date", "hour"],
            )


def downgrade():
    for table_name in TABLES:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.drop_constraint(OLD_UNIQUES[table_name], type_="unique")
            batch_op.create_unique_constraint(
                OLD_UNIQUES[table_name],
                ["plaza_name", "date", "hour"],
            )
            batch_op.drop_index(batch_op.f(f"ix_{table_name}_plaza_identifier"))
            batch_op.drop_column("plaza_identifier")
