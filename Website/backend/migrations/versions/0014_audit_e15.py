"""seed audit exception type E15

Revision ID: 0014_audit_e15
Revises: 0013_plaza_daily_revenue
Create Date: 2026-09-18 10:58:00.000000

"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision = "0014_audit_e15"
down_revision = "0013_plaza_daily_revenue"
branch_labels = None
depends_on = None

NEW_TYPES = (
    (
        "E15",
        "Same vehicles get exempted while user fee is collected at "
        "subsequent plaza in same journey",
        15,
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
    op.execute(sa.text("DELETE FROM audit_exception_types WHERE code = 'E15'"))
