"""Plaza master under an SPV."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.extensions import db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Plaza(db.Model):
    __tablename__ = "plazas"

    id = db.Column(db.Integer, primary_key=True)
    plaza_identifier = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    # One SPV can own many plazas.
    spv_identifier = db.Column(
        db.String(36),
        db.ForeignKey("spvs.spv_identifier", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    plaza_name = db.Column(db.String(255), nullable=False)
    plaza_code = db.Column(db.String(100), nullable=True)
    chainage = db.Column(db.String(100), nullable=True)
    district_state = db.Column(db.String(255), nullable=True)
    latitude = db.Column(db.String(50), nullable=True)
    longitude = db.Column(db.String(50), nullable=True)
    tolling_start_date = db.Column(db.Date, nullable=True)
    total_lanes = db.Column(db.Integer, nullable=True)
    lhs_rhs_split = db.Column(db.String(100), nullable=True)
    hybrid_etc_only = db.Column(db.String(100), nullable=True)
    shift_pattern = db.Column(db.String(255), nullable=True)
    toll_day_cutoff = db.Column(db.String(100), nullable=True)
    om_contractor = db.Column(db.String(255), nullable=True)
    source_daily_tms_report = db.Column(db.Text, nullable=True)
    event_calendar = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    spv = db.relationship(
        "Spv",
        back_populates="plazas",
        foreign_keys=[spv_identifier],
        primaryjoin="Plaza.spv_identifier == Spv.spv_identifier",
    )

    def to_dict(self, *, include_spv: bool = True) -> dict:
        payload = {
            "id": self.id,
            "plaza_identifier": self.plaza_identifier,
            "spv_identifier": self.spv_identifier,
            "plaza_name": self.plaza_name,
            "plaza_code": self.plaza_code,
            "chainage": self.chainage,
            "district_state": self.district_state,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "tolling_start_date": (
                self.tolling_start_date.isoformat() if self.tolling_start_date else None
            ),
            "total_lanes": self.total_lanes,
            "lhs_rhs_split": self.lhs_rhs_split,
            "hybrid_etc_only": self.hybrid_etc_only,
            "shift_pattern": self.shift_pattern,
            "toll_day_cutoff": self.toll_day_cutoff,
            "om_contractor": self.om_contractor,
            "source_daily_tms_report": self.source_daily_tms_report,
            "event_calendar": self.event_calendar,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_spv and self.spv is not None:
            payload["parent_spv"] = {
                "spv_identifier": self.spv.spv_identifier,
                "spv_name": self.spv.spv_name,
                "company_identifier": self.spv.company_identifier,
            }
        return payload

    def __repr__(self) -> str:
        return f"<Plaza {self.plaza_name}>"
