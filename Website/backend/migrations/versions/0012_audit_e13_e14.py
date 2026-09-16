"""seed audit exception types E13 and E14

Revision ID: 0012_audit_e13_e14
Revises: 0011_plaza_date_idx
Create Date: 2026-09-16 15:05:00.000000

"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision = "0012_audit_e13_e14"
down_revision = "0011_plaza_date_idx"
branch_labels = None
depends_on = None

NEW_TYPES = (
    (
        "E13",
        "Same vehicles get exempted while toll fee is collected at same plaza",
        13,
    ),
    (
        "E14",
        "Same vehicles get exempted under multiple class exemption",
        14,
    ),
)


def upgrade():
    now = datetime.now(timezone.utc)
    types_table = sa.table(
        "audit_exception_types",
        sa.column("code", sa.String),
        sa.column("label", sa.String),
        sa.column("description", sa.Text),
        sa.column("sort_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    conn = op.get_bind()
    existing = {
        row[0]
        for row in conn.execute(sa.text("SELECT code FROM audit_exception_types")).fetchall()
    }
    to_insert = [
        {
            "code": code,
            "label": label,
            "description": None,
            "sort_order": sort_order,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        for code, label, sort_order in NEW_TYPES
        if code not in existing
    ]
    if to_insert:
        op.bulk_insert(types_table, to_insert)


def downgrade():
    op.execute(
        sa.text(
            "DELETE FROM audit_exception_types WHERE code IN ('E13', 'E14')"
        )
    )
