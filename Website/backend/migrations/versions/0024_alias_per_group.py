"""Allow the same alias text on different groups in one config section.

Revision ID: 0024_alias_per_group
Revises: 0023_mapping_config
Create Date: 2026-10-28

A header such as "NPCI Vehicle Class" can belong to both the vehicle-class
column group and the NPCI class group. Uniqueness stays inside one group.
"""

from __future__ import annotations

from alembic import op

revision = "0024_alias_per_group"
down_revision = "0023_mapping_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_mapping_aliases_domain_norm",
        "mapping_aliases",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_mapping_aliases_canonical_norm",
        "mapping_aliases",
        ["canonical_id", "alias_normalized"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_mapping_aliases_canonical_norm",
        "mapping_aliases",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_mapping_aliases_domain_norm",
        "mapping_aliases",
        ["domain_id", "alias_normalized"],
    )
