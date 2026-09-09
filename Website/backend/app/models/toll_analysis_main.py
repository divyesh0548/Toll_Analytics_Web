"""Hourly toll analytics fact table (formerly nhit_analysis)."""

from __future__ import annotations

from app.extensions import db

_INT0 = dict(nullable=False, default=0, server_default="0")


class TollAnalysisMain(db.Model):
    """One row per plaza + date + hour with class / lane / MOP counts."""

    __tablename__ = "toll_analysis_main"
    __table_args__ = (
        db.UniqueConstraint(
            "plaza_name",
            "date",
            "hour",
            name="uq_toll_analysis_main_plaza_date_hour",
        ),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    plaza_name = db.Column(db.Text, nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    hour = db.Column(db.Text, nullable=False)
    total_transaction = db.Column(db.Integer, **_INT0)

    vc_3wheeler = db.Column(db.Integer, **_INT0)
    vc_bus_2_axle = db.Column(db.Integer, **_INT0)
    vc_car_jeep = db.Column(db.Integer, **_INT0)
    vc_lcv = db.Column(db.Integer, **_INT0)
    vc_tractor = db.Column(db.Integer, **_INT0)
    vc_truck_4_6_axle = db.Column(db.Integer, **_INT0)
    vc_truck_2_axle = db.Column(db.Integer, **_INT0)
    vc_truck_3_axle = db.Column(db.Integer, **_INT0)

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

    mop_fastag = db.Column(db.Integer, **_INT0)
    mop_cash = db.Column(db.Integer, **_INT0)
    mop_upi = db.Column(db.Integer, **_INT0)
    mop_exempt = db.Column(db.Integer, **_INT0)

    def __repr__(self) -> str:
        return f"<TollAnalysisMain {self.plaza_name} {self.date} {self.hour}>"
