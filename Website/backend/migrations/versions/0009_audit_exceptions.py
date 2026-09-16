"""create audit exception types and monthly plaza metrics

Revision ID: 0009_audit_exceptions
Revises: 0008_replace_analytics_tables
Create Date: 2026-09-15 11:40:00.000000

"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision = "0009_audit_exceptions"
down_revision = "0008_replace_analytics_tables"
branch_labels = None
depends_on = None

CATALOG = [
    ("E01", "Ineligible exemptions provided to non-commercial local users", 1),
    ("E02", "Ineligible exemptions provided to non-local non-commercial users", 2),
    ("E03", "Ineligible exemptions provided to commercial vehicles", 3),
    ("E04", "Local passes wrongly issued to commercial vehicles", 4),
    ("E05", "Incorrect FASTag issuance by the issuer banks", 5),
    (
        "E06",
        "50% discounted passes wrongly issued to commercial vehicles not "
        "registered within the district or having a national permit",
        6,
    ),
    ("E07", "Local passes issued at a lower or zero charge", 7),
    (
        "E08",
        "Local passes issued to users not owning the vehicle or residing beyond 20 km",
        8,
    ),
    ("E09", "Revenue loss due to transactions not getting settled", 9),
    ("E10", "Short imposition of overloading penalty", 10),
    (
        "E11",
        "AVC failure to detect the correct class, or higher class detected "
        "but no violation raised",
        11,
    ),
    (
        "E12",
        "Multiple FASTags issued to same vehicle (lower class tags) "
        "resulting in revenue loss",
        12,
    ),
]


def upgrade():
    op.create_table(
        "audit_exception_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_exception_types_code"),
        "audit_exception_types",
        ["code"],
        unique=True,
    )

    op.create_table(
        "audit_exception_metrics",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("plaza_identifier", sa.String(length=36), nullable=False),
        sa.Column("exception_type_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "month >= 1 AND month <= 12",
            name="ck_audit_exception_metrics_month",
        ),
        sa.CheckConstraint(
            "year >= 1990 AND year <= 2100",
            name="ck_audit_exception_metrics_year",
        ),
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
        sa.UniqueConstraint(
            "plaza_identifier",
            "exception_type_id",
            "year",
            "month",
            name="uq_audit_exception_metrics_plaza_type_period",
        ),
    )
    op.create_index(
        op.f("ix_audit_exception_metrics_plaza_identifier"),
        "audit_exception_metrics",
        ["plaza_identifier"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_exception_metrics_exception_type_id"),
        "audit_exception_metrics",
        ["exception_type_id"],
        unique=False,
    )

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
    op.bulk_insert(
        types_table,
        [
            {
                "code": code,
                "label": label,
                "description": None,
                "sort_order": sort_order,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
            for code, label, sort_order in CATALOG
        ],
    )


def downgrade():
    op.drop_index(
        op.f("ix_audit_exception_metrics_exception_type_id"),
        table_name="audit_exception_metrics",
    )
    op.drop_index(
        op.f("ix_audit_exception_metrics_plaza_identifier"),
        table_name="audit_exception_metrics",
    )
    op.drop_table("audit_exception_metrics")
    op.drop_index(op.f("ix_audit_exception_types_code"), table_name="audit_exception_types")
    op.drop_table("audit_exception_types")
