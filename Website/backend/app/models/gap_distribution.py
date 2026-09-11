"""Hourly average gap (and <2s counts) per lane."""

from __future__ import annotations

from app.extensions import db

_INT0 = dict(nullable=False, default=0, server_default="0")


class GapDistributionPerLane(db.Model):
    """One row per plaza + date + hour; l01…l12 avg seconds, *_lt2_count counts."""

    __tablename__ = "gap_distribution_per_lane"
    __table_args__ = (
        db.UniqueConstraint(
            "plaza_identifier",
            "date",
            "hour",
            name="uq_gap_distribution_per_lane",
        ),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    plaza_identifier = db.Column(db.Text, nullable=False, index=True)
    plaza_name = db.Column(db.Text, nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    hour = db.Column(db.Text, nullable=False)

    l01 = db.Column(db.Float, nullable=True)
    l02 = db.Column(db.Float, nullable=True)
    l03 = db.Column(db.Float, nullable=True)
    l04 = db.Column(db.Float, nullable=True)
    l05 = db.Column(db.Float, nullable=True)
    l06 = db.Column(db.Float, nullable=True)
    l07 = db.Column(db.Float, nullable=True)
    l08 = db.Column(db.Float, nullable=True)
    l09 = db.Column(db.Float, nullable=True)
    l10 = db.Column(db.Float, nullable=True)
    l11 = db.Column(db.Float, nullable=True)
    l12 = db.Column(db.Float, nullable=True)

    l01_lt2_count = db.Column(db.Integer, **_INT0)
    l02_lt2_count = db.Column(db.Integer, **_INT0)
    l03_lt2_count = db.Column(db.Integer, **_INT0)
    l04_lt2_count = db.Column(db.Integer, **_INT0)
    l05_lt2_count = db.Column(db.Integer, **_INT0)
    l06_lt2_count = db.Column(db.Integer, **_INT0)
    l07_lt2_count = db.Column(db.Integer, **_INT0)
    l08_lt2_count = db.Column(db.Integer, **_INT0)
    l09_lt2_count = db.Column(db.Integer, **_INT0)
    l10_lt2_count = db.Column(db.Integer, **_INT0)
    l11_lt2_count = db.Column(db.Integer, **_INT0)
    l12_lt2_count = db.Column(db.Integer, **_INT0)

    def __repr__(self) -> str:
        return f"<GapDistributionPerLane {self.plaza_identifier} {self.date} {self.hour}>"
