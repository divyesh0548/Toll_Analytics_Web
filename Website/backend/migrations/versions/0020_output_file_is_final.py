"""Add is_final_output to audit_exception_output_files (staging vs downloadable).

Revision ID: 0020_output_is_final
Revises: 0019_exception_jobs
Create Date: 2026-10-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_output_is_final"
down_revision = "0019_exception_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_exception_output_files",
        sa.Column(
            "is_final_output",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.create_index(
        "ix_audit_exception_output_files_is_final",
        "audit_exception_output_files",
        ["is_final_output"],
    )
    op.create_index(
        "ix_audit_exception_output_files_plaza_type_final_created",
        "audit_exception_output_files",
        ["plaza_identifier", "exception_type_id", "is_final_output", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audit_exception_output_files_plaza_type_final_created",
        table_name="audit_exception_output_files",
    )
    op.drop_index(
        "ix_audit_exception_output_files_is_final",
        table_name="audit_exception_output_files",
    )
    op.drop_column("audit_exception_output_files", "is_final_output")
