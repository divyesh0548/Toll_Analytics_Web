"""Plaza calendar events (holidays, mela windows, etc.)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


EVENT_TYPES: tuple[str, ...] = (
    "national_holiday",
    "regional_holiday",
    "bank_holiday",
    "govt_holiday",
    "election_day",
    "mela_window",
)

EVENT_SOURCES: tuple[str, ...] = ("upload", "manual")


class PlazaCalendarEvent(db.Model):
    __tablename__ = "plaza_calendar_events"
    __table_args__ = (
        db.CheckConstraint(
            "end_date >= start_date",
            name="ck_plaza_calendar_events_date_range",
        ),
        db.Index(
            "ix_plaza_calendar_events_plaza_start",
            "plaza_identifier",
            "start_date",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    plaza_identifier = db.Column(
        db.String(36),
        db.ForeignKey("plazas.plaza_identifier", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label = db.Column(db.String(255), nullable=False)
    event_type = db.Column(db.String(50), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    source = db.Column(db.String(20), nullable=False, default="manual")
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
            "label": self.label,
            "event_type": self.event_type,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<PlazaCalendarEvent {self.label} "
            f"{self.start_date}–{self.end_date} plaza={self.plaza_identifier}>"
        )
