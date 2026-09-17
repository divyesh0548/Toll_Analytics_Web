"""Daily plaza revenue (synced from source snt_form submissions)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PlazaDailyRevenue(db.Model):
    """One revenue total per plaza per calendar day."""

    __tablename__ = "plaza_daily_revenue"
    __table_args__ = (
        db.UniqueConstraint(
            "plaza_identifier",
            "date",
            name="uq_plaza_daily_revenue_plaza_date",
        ),
        db.Index(
            "ix_plaza_daily_revenue_plaza_date",
            "plaza_identifier",
            "date",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    plaza_identifier = db.Column(
        db.String(36),
        db.ForeignKey("plazas.plaza_identifier", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date = db.Column(db.Date, nullable=False, index=True)
    revenue = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "plaza_identifier": self.plaza_identifier,
            "date": self.date.isoformat() if self.date else None,
            "revenue": float(self.revenue) if self.revenue is not None else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<PlazaDailyRevenue plaza={self.plaza_identifier} "
            f"date={self.date} revenue={self.revenue}>"
        )
