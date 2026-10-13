"""Track parallel plaza-analytics job on pipeline batches.

Revision ID: 0022_pipeline_analytics_job
Revises: 0021_exception_pipeline
Create Date: 2026-10-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_pipeline_analytics_job"
down_revision = "0021_exception_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exception_pipeline_batches",
        sa.Column("analytics_job_uuid", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_exception_pipeline_batches_analytics_job_uuid",
        "exception_pipeline_batches",
        ["analytics_job_uuid"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exception_pipeline_batches_analytics_job_uuid",
        table_name="exception_pipeline_batches",
    )
    op.drop_column("exception_pipeline_batches", "analytics_job_uuid")
