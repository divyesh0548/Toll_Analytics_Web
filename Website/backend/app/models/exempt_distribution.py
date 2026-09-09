"""Hourly exempt vehicle counts per lane."""

from __future__ import annotations

from app.extensions import db

_INT0 = dict(nullable=False, default=0, server_default="0")


class ExemptDistributionPerLane(db.Model):
    """One row per plaza + date + hour; l01…l12 hold exempt counts."""

    __tablename__ = "exempt_distribution_per_lane"
    __table_args__ = (
        db.UniqueConstraint(
            "plaza_name",
            "date",
            "hour",
            name="uq_exempt_distribution_plaza_date_hour",
        ),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    plaza_name = db.Column(db.Text, nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    hour = db.Column(db.Text, nullable=False)

    l01 = db.Column(db.Integer, **_INT0)
    l02 = db.Column(db.Integer, **_INT0)
    l03 = db.Column(db.Integer, **_INT0)
    l04 = db.Column(db.Integer, **_INT0)
    l05 = db.Column(db.Integer, **_INT0)
    l06 = db.Column(db.Integer, **_INT0)
    l07 = db.Column(db.Integer, **_INT0)
    l08 = db.Column(db.Integer, **_INT0)
    l09 = db.Column(db.Integer, **_INT0)
    l10 = db.Column(db.Integer, **_INT0)
    l11 = db.Column(db.Integer, **_INT0)
    l12 = db.Column(db.Integer, **_INT0)

    def __repr__(self) -> str:
        return f"<ExemptDistributionPerLane {self.plaza_name} {self.date} {self.hour}>"
