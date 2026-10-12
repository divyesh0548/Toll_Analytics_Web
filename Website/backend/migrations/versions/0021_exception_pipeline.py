"""Monthly exception inputs, pipeline batches, and parallel metrics/outputs.

Revision ID: 0021_exception_pipeline
Revises: 0020_output_is_final
Create Date: 2026-10-12

Does not alter existing audit_exception_metrics / output_files / exception_jobs.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_exception_pipeline"
down_revision = "0020_output_is_final"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plaza_monthly_exception_inputs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("plaza_identifier", sa.String(36), sa.ForeignKey("plazas.plaza_identifier", ondelete="CASCADE"), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("slot", sa.String(64), nullable=False),
        sa.Column("original_file_name", sa.String(512), nullable=False),
        sa.Column("s3_key", sa.String(1024), nullable=False),
        sa.Column("file_url", sa.String(2048), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="upload"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_plaza_monthly_exc_inputs_month"),
        sa.CheckConstraint("year >= 1990 AND year <= 2100", name="ck_plaza_monthly_exc_inputs_year"),
    )
    op.create_index(
        "ix_plaza_monthly_exc_inputs_plaza_period",
        "plaza_monthly_exception_inputs",
        ["plaza_identifier", "year", "month"],
    )
    op.create_index(
        "ix_plaza_monthly_exc_inputs_plaza_period_slot",
        "plaza_monthly_exception_inputs",
        ["plaza_identifier", "year", "month", "slot"],
    )

    op.create_table(
        "exception_pipeline_batches",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("batch_uuid", sa.String(36), nullable=False),
        sa.Column("plaza_identifier", sa.String(36), sa.ForeignKey("plazas.plaza_identifier", ondelete="RESTRICT"), nullable=False),
        sa.Column("pipeline_plaza_key", sa.String(100), nullable=True),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("continue_on_failure", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("batch_uuid", name="uq_exception_pipeline_batches_uuid"),
        sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_pipeline_batches_month"),
    )
    op.create_index("ix_exception_pipeline_batches_status", "exception_pipeline_batches", ["status"])
    op.create_index(
        "ix_exception_pipeline_batches_plaza_period",
        "exception_pipeline_batches",
        ["plaza_identifier", "year", "month"],
    )

    op.create_table(
        "exception_pipeline_batch_steps",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.BigInteger(), sa.ForeignKey("exception_pipeline_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("program_code", sa.String(64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("child_job_uuid", sa.String(36), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("batch_id", "program_code", name="uq_pipeline_batch_steps_program"),
    )
    op.create_index("ix_pipeline_batch_steps_batch", "exception_pipeline_batch_steps", ["batch_id"])
    op.create_index("ix_pipeline_batch_steps_status", "exception_pipeline_batch_steps", ["status"])

    # Parallel metrics / outputs — same shape as legacy tables, separate namespace.
    op.create_table(
        "pipeline_audit_exception_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("plaza_identifier", sa.String(36), sa.ForeignKey("plazas.plaza_identifier", ondelete="CASCADE"), nullable=False),
        sa.Column("exception_type_id", sa.Integer(), sa.ForeignKey("audit_exception_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=True),
        sa.Column("percentage", sa.Numeric(8, 2), nullable=True),
        sa.Column("severity", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint(
            "plaza_identifier",
            "exception_type_id",
            "year",
            "month",
            name="uq_pipeline_audit_exception_metrics_plaza_type_period",
        ),
        sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_pipeline_aem_month"),
        sa.CheckConstraint("year >= 1990 AND year <= 2100", name="ck_pipeline_aem_year"),
    )
    op.create_index(
        "ix_pipeline_aem_plaza",
        "pipeline_audit_exception_metrics",
        ["plaza_identifier"],
    )
    op.create_index(
        "ix_pipeline_aem_type",
        "pipeline_audit_exception_metrics",
        ["exception_type_id"],
    )

    op.create_table(
        "pipeline_audit_exception_output_files",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("plaza_identifier", sa.String(36), sa.ForeignKey("plazas.plaza_identifier", ondelete="CASCADE"), nullable=False),
        sa.Column("exception_type_id", sa.Integer(), sa.ForeignKey("audit_exception_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("month_label", sa.String(64), nullable=False),
        sa.Column("file_name", sa.String(512), nullable=False),
        sa.Column("s3_key", sa.String(1024), nullable=False),
        sa.Column("file_url", sa.String(2048), nullable=False),
        sa.Column("original_file_name", sa.String(512), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("is_final_output", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index(
        "ix_pipeline_aeof_plaza",
        "pipeline_audit_exception_output_files",
        ["plaza_identifier"],
    )
    op.create_index(
        "ix_pipeline_aeof_type",
        "pipeline_audit_exception_output_files",
        ["exception_type_id"],
    )


def downgrade() -> None:
    op.drop_table("pipeline_audit_exception_output_files")
    op.drop_table("pipeline_audit_exception_metrics")
    op.drop_table("exception_pipeline_batch_steps")
    op.drop_table("exception_pipeline_batches")
    op.drop_table("plaza_monthly_exception_inputs")
