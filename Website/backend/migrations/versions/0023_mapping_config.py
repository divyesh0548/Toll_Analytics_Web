"""Shared mapping tables for editable vehicle class, MOP, aliases, keywords.

Revision ID: 0023_mapping_config
Revises: 0022_pipeline_analytics_job
Create Date: 2026-10-27

Empty tables only. Seed with: flask --app run:app seed-shared-config
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_mapping_config"
down_revision = "0022_pipeline_analytics_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mapping_domains",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_mapping_domains_code"),
    )
    op.create_index("ix_mapping_domains_code", "mapping_domains", ["code"])

    op.create_table(
        "mapping_canonicals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("domain_id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_key", sa.String(128), nullable=False),
        sa.Column("db_column", sa.String(128), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["domain_id"], ["mapping_domains.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "domain_id", "canonical_key", name="uq_mapping_canonicals_domain_key"
        ),
    )
    op.create_index(
        "ix_mapping_canonicals_domain_id", "mapping_canonicals", ["domain_id"]
    )

    op.create_table(
        "mapping_aliases",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("domain_id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_id", sa.BigInteger(), nullable=False),
        sa.Column("alias", sa.String(512), nullable=False),
        sa.Column("alias_normalized", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["domain_id"], ["mapping_domains.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["canonical_id"], ["mapping_canonicals.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "domain_id", "alias_normalized", name="uq_mapping_aliases_domain_norm"
        ),
    )
    op.create_index("ix_mapping_aliases_domain_id", "mapping_aliases", ["domain_id"])
    op.create_index(
        "ix_mapping_aliases_canonical_id", "mapping_aliases", ["canonical_id"]
    )

    op.create_table(
        "mapping_list_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("domain_id", sa.BigInteger(), nullable=False),
        sa.Column("list_key", sa.String(64), nullable=False),
        sa.Column("value", sa.String(512), nullable=False),
        sa.Column("value_normalized", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["domain_id"], ["mapping_domains.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "domain_id",
            "list_key",
            "value_normalized",
            name="uq_mapping_list_items_domain_key_norm",
        ),
    )
    op.create_index(
        "ix_mapping_list_items_domain_id", "mapping_list_items", ["domain_id"]
    )

    op.create_table(
        "mapping_settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )

    op.create_table(
        "mapping_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("domain_code", sa.String(64), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("mapping_audit")
    op.drop_table("mapping_settings")
    op.drop_index("ix_mapping_list_items_domain_id", table_name="mapping_list_items")
    op.drop_table("mapping_list_items")
    op.drop_index("ix_mapping_aliases_canonical_id", table_name="mapping_aliases")
    op.drop_index("ix_mapping_aliases_domain_id", table_name="mapping_aliases")
    op.drop_table("mapping_aliases")
    op.drop_index("ix_mapping_canonicals_domain_id", table_name="mapping_canonicals")
    op.drop_table("mapping_canonicals")
    op.drop_index("ix_mapping_domains_code", table_name="mapping_domains")
    op.drop_table("mapping_domains")
