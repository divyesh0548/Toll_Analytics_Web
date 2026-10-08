"""exception processing jobs and input file registry

Revision ID: 0019_exception_jobs
Revises: 0018_exc_output_files
Create Date: 2026-10-08 16:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0019_exception_jobs"
down_revision = "0018_exc_output_files"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "exception_jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("job_uuid", sa.String(length=36), nullable=False),
        sa.Column("program_code", sa.String(length=64), nullable=False),
        sa.Column("plaza_identifier", sa.String(length=36), nullable=False),
        sa.Column("pipeline_plaza_key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("process_name", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["plaza_identifier"],
            ["plazas.plaza_identifier"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_uuid"),
    )
    op.create_index(
        op.f("ix_exception_jobs_job_uuid"),
        "exception_jobs",
        ["job_uuid"],
        unique=False,
    )
    op.create_index(
        op.f("ix_exception_jobs_program_code"),
        "exception_jobs",
        ["program_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_exception_jobs_plaza_identifier"),
        "exception_jobs",
        ["plaza_identifier"],
        unique=False,
    )
    op.create_index(
        op.f("ix_exception_jobs_status"),
        "exception_jobs",
        ["status"],
        unique=False,
    )

    op.create_table(
        "exception_job_files",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("slot", sa.String(length=64), nullable=False),
        sa.Column("original_file_name", sa.String(length=512), nullable=False),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        sa.Column("file_url", sa.String(length=2048), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["exception_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_exception_job_files_job_id"),
        "exception_job_files",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_exception_job_files_slot"),
        "exception_job_files",
        ["slot"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_exception_job_files_slot"), table_name="exception_job_files")
    op.drop_index(op.f("ix_exception_job_files_job_id"), table_name="exception_job_files")
    op.drop_table("exception_job_files")
    op.drop_index(op.f("ix_exception_jobs_status"), table_name="exception_jobs")
    op.drop_index(op.f("ix_exception_jobs_plaza_identifier"), table_name="exception_jobs")
    op.drop_index(op.f("ix_exception_jobs_program_code"), table_name="exception_jobs")
    op.drop_index(op.f("ix_exception_jobs_job_uuid"), table_name="exception_jobs")
    op.drop_table("exception_jobs")
