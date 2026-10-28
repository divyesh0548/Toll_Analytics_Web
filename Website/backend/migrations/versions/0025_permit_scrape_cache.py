"""Shared permit scrape results, not tied to a plaza.

Revision ID: 0025_permit_scrape_cache
Revises: 0024_alias_per_group
Create Date: 2026-10-28

E6 looks up a vehicle here before scraping, and writes newly scraped
permit rows while a scrape is still running.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_permit_scrape_cache"
down_revision = "0024_alias_per_group"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "permit_scrape_cache",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("vehicle_reg_no", sa.String(length=32), nullable=False),
        sa.Column("permit_type", sa.Text(), nullable=True),
        sa.Column("permit_authorization_no", sa.Text(), nullable=True),
        sa.Column("permit_validity", sa.Text(), nullable=True),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "vehicle_reg_no", name="uq_permit_scrape_cache_vehicle"
        ),
    )


def downgrade() -> None:
    op.drop_table("permit_scrape_cache")
