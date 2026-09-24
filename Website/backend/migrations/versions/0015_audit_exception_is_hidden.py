"""add is_hidden to audit_exception_types

Revision ID: 0015_audit_exception_is_hidden
Revises: 0014_audit_e15
Create Date: 2026-09-23 10:55:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0015_audit_exception_is_hidden"
down_revision = "0014_audit_e15"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "audit_exception_types",
        sa.Column(
            "is_hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade():
    op.drop_column("audit_exception_types", "is_hidden")
