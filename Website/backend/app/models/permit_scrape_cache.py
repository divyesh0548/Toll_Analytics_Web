"""Plaza-agnostic permit rows scraped for E6."""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PermitScrapeCache(db.Model):
    __tablename__ = "permit_scrape_cache"
    __table_args__ = (
        db.UniqueConstraint(
            "vehicle_reg_no", name="uq_permit_scrape_cache_vehicle"
        ),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    vehicle_reg_no = db.Column(db.String(32), nullable=False)
    permit_type = db.Column(db.Text, nullable=True)
    permit_authorization_no = db.Column(db.Text, nullable=True)
    permit_validity = db.Column(db.Text, nullable=True)
    scraped_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utc_now
    )
