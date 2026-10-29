"""Rates and approved-exemption workbooks stored per plaza and date range.

Revision ID: 0026_plaza_reference_files
Revises: 0025_permit_scrape_cache
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_plaza_reference_files"
down_revision = "0025_permit_scrape_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plaza_reference_files",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("plaza_identifier", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("original_file_name", sa.String(length=255), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["plaza_identifier"],
            ["plazas.plaza_identifier"],
            name="fk_plaza_reference_files_plaza",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            name="fk_plaza_reference_files_user",
        ),
        sa.CheckConstraint(
            "kind IN ('rates', 'approved_exemption')",
            name="ck_plaza_reference_files_kind",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_plaza_reference_files_dates",
        ),
    )
    op.create_index(
        "ix_plaza_reference_files_plaza_kind",
        "plaza_reference_files",
        ["plaza_identifier", "kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_plaza_reference_files_plaza_kind",
        table_name="plaza_reference_files",
    )
    op.drop_table("plaza_reference_files")
