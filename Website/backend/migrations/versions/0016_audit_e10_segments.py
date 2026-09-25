"""add E10 internal segments A, B, and C

Revision ID: 0016_audit_e10_segments
Revises: 0015_audit_exception_is_hidden
Create Date: 2026-09-25 11:05:00.000000

"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision = "0016_audit_e10_segments"
down_revision = "0015_audit_exception_is_hidden"
branch_labels = None
depends_on = None

SEGMENTS = (
    ("E10-A", "SWB weight greater than standard weight", 1),
    ("E10-B", "SWB weight is zero", 2),
    (
        "E10-C",
        "SWB weight greater than zero and less than standard weight",
        3,
    ),
)


def upgrade():
    op.add_column(
        "audit_exception_types",
        sa.Column("parent_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_audit_exception_types_parent_id",
        "audit_exception_types",
        "audit_exception_types",
        ["parent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_audit_exception_types_parent_id",
        "audit_exception_types",
        ["parent_id"],
        unique=False,
    )

    now = datetime.now(timezone.utc)
    conn = op.get_bind()
    parent_id = conn.execute(
        sa.text("SELECT id FROM audit_exception_types WHERE code = 'E10'")
    ).scalar()
    if parent_id is None:
        raise RuntimeError("audit_exception_types is missing E10; cannot add segments.")

    existing = {
        row[0]
        for row in conn.execute(sa.text("SELECT code FROM audit_exception_types")).fetchall()
    }
    for code, label, sort_order in SEGMENTS:
        if code in existing:
            conn.execute(
                sa.text(
                    """
                    UPDATE audit_exception_types
                    SET label = :label,
                        sort_order = :sort_order,
                        parent_id = :parent_id,
                        is_active = TRUE,
                        updated_at = :updated_at
                    WHERE code = :code
                    """
                ),
                {
                    "label": label,
                    "sort_order": sort_order,
                    "parent_id": parent_id,
                    "updated_at": now,
                    "code": code,
                },
            )
            continue
        conn.execute(
            sa.text(
                """
                INSERT INTO audit_exception_types (
                    code, label, description, sort_order, is_active,
                    is_hidden, parent_id, created_at, updated_at
                )
                VALUES (
                    :code, :label, NULL, :sort_order, TRUE,
                    FALSE, :parent_id, :created_at, :updated_at
                )
                """
            ),
            {
                "code": code,
                "label": label,
                "sort_order": sort_order,
                "parent_id": parent_id,
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade():
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM audit_exception_metrics
            WHERE exception_type_id IN (
                SELECT id FROM audit_exception_types
                WHERE code IN ('E10-A', 'E10-B', 'E10-C')
            )
            """
        )
    )
    conn.execute(
        sa.text(
            "DELETE FROM audit_exception_types WHERE code IN ('E10-A', 'E10-B', 'E10-C')"
        )
    )
    op.drop_index("ix_audit_exception_types_parent_id", table_name="audit_exception_types")
    op.drop_constraint(
        "fk_audit_exception_types_parent_id",
        "audit_exception_types",
        type_="foreignkey",
    )
    op.drop_column("audit_exception_types", "parent_id")
