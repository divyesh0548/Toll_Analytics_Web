"""Hourly MOP counts broken down by lane."""

from __future__ import annotations

from app.extensions import db

_INT0 = dict(nullable=False, default=0, server_default="0")


class MopDistributionPerLane(db.Model):
    """One row per plaza + date + hour + lane + mop."""

    __tablename__ = "mop_distribution_per_lane"
    __table_args__ = (
        db.UniqueConstraint(
            "plaza_identifier",
            "date",
            "hour",
            "lane",
            "mop",
            name="uq_mop_distribution_per_lane",
        ),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    plaza_identifier = db.Column(db.Text, nullable=False, index=True)
    plaza_name = db.Column(db.Text, nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    hour = db.Column(db.Text, nullable=False)
    lane = db.Column(db.Text, nullable=False)
    mop = db.Column(db.Text, nullable=False)
    txn_count = db.Column(db.Integer, **_INT0)

    def __repr__(self) -> str:
        return (
            f"<MopDistributionPerLane {self.plaza_identifier} "
            f"{self.lane}/{self.mop} {self.date} {self.hour}>"
        )
