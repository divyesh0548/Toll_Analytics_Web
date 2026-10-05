"""store S3 URLs for exception program output files

Revision ID: 0018_audit_exception_output_files
Revises: 0017_audit_metric_percentage
Create Date: 2026-10-05 12:40:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0018_exc_output_files"
down_revision = "0017_audit_metric_percentage"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_exception_output_files",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("plaza_identifier", sa.String(length=36), nullable=False),
        sa.Column("exception_type_id", sa.Integer(), nullable=False),
        # e.g. Jan-2026 or Jan-Mar-2026 — one file can cover many months
        sa.Column("month_label", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        # Permanent object URL (not presigned). Bucket access still required to download.
        sa.Column("file_url", sa.String(length=2048), nullable=False),
        sa.Column("original_file_name", sa.String(length=512), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["exception_type_id"],
            ["audit_exception_types.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plaza_identifier"],
            ["plazas.plaza_identifier"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_exception_output_files_plaza_identifier"),
        "audit_exception_output_files",
        ["plaza_identifier"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_exception_output_files_exception_type_id"),
        "audit_exception_output_files",
        ["exception_type_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_exception_output_files_plaza_type_created",
        "audit_exception_output_files",
        ["plaza_identifier", "exception_type_id", "created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_audit_exception_output_files_plaza_type_created",
        table_name="audit_exception_output_files",
    )
    op.drop_index(
        op.f("ix_audit_exception_output_files_exception_type_id"),
        table_name="audit_exception_output_files",
    )
    op.drop_index(
        op.f("ix_audit_exception_output_files_plaza_identifier"),
        table_name="audit_exception_output_files",
    )
    op.drop_table("audit_exception_output_files")
