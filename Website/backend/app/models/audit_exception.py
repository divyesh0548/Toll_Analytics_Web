"""Audit exception type catalog and monthly plaza metrics."""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Canonical findings — seeded on migrate / app startup.
AUDIT_EXCEPTION_CATALOG: list[dict] = [
    {
        "code": "E01",
        "label": "Ineligible exemptions provided to non-commercial local users",
        "sort_order": 1,
    },
    {
        "code": "E02",
        "label": "Ineligible exemptions provided to non-local non-commercial users",
        "sort_order": 2,
    },
    {
        "code": "E03",
        "label": "Ineligible exemptions provided to commercial vehicles",
        "sort_order": 3,
    },
    {
        "code": "E04",
        "label": "Local passes wrongly issued to commercial vehicles",
        "sort_order": 4,
    },
    {
        "code": "E05",
        "label": "Incorrect FASTag issuance by the issuer banks",
        "sort_order": 5,
    },
    {
        "code": "E06",
        "label": (
            "50% discounted passes wrongly issued to commercial vehicles not "
            "registered within the district or having a national permit"
        ),
        "sort_order": 6,
    },
    {
        "code": "E07",
        "label": "Local passes issued at a lower or zero charge",
        "sort_order": 7,
    },
    {
        "code": "E08",
        "label": "Local passes issued to users not owning the vehicle or residing beyond 20 km",
        "sort_order": 8,
    },
    {
        "code": "E09",
        "label": "Revenue loss due to transactions not getting settled",
        "sort_order": 9,
    },
    {
        "code": "E10",
        "label": "Short imposition of overloading penalty",
        "sort_order": 10,
    },
    {
        "code": "E11",
        "label": (
            "AVC failure to detect the correct class, or higher class detected "
            "but no violation raised"
        ),
        "sort_order": 11,
    },
    {
        "code": "E12",
        "label": (
            "Multiple FASTags issued to same vehicle (lower class tags) "
            "resulting in revenue loss"
        ),
        "sort_order": 12,
    },
    {
        "code": "E13",
        "label": (
            "Same vehicles get exempted while toll fee is collected at same "
            "plaza on different occasion"
        ),
        "sort_order": 13,
    },
    {
        "code": "E14",
        "label": "Same vehicles get exempted under multiple class exemption",
        "sort_order": 14,
    },
    {
        "code": "E15",
        "label": (
            "Same vehicles get exempted while user fee is collected at "
            "subsequent plaza in same journey"
        ),
        "sort_order": 15,
    },
]


# Internal segments of E10. parent_code is resolved to parent_id on seed.
E10_SEGMENT_CATALOG: list[dict] = [
    {
        "code": "E10-A",
        "label": "Lane/Chg standard weight less than standard weight",
        "sort_order": 1,
        "parent_code": "E10",
    },
    {
        "code": "E10-B",
        "label": (
            "Lane/Chg standard weight at or above standard weight "
            "and SWB weight is zero"
        ),
        "sort_order": 2,
        "parent_code": "E10",
    },
    {
        "code": "E10-C",
        "label": (
            "Lane/Chg standard weight at or above standard weight "
            "and SWB weight is not zero"
        ),
        "sort_order": 3,
        "parent_code": "E10",
    },
]


class AuditExceptionType(db.Model):
    __tablename__ = "audit_exception_types"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(16), unique=True, nullable=False, index=True)
    label = db.Column(db.String(512), nullable=False)
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # When True, keep type + metrics in DB but omit from website Audit Exceptions UI.
    is_hidden = db.Column(db.Boolean, nullable=False, default=False)
    # Set for internal segments (E10-A/B/C). Null for top-level findings such as E10.
    parent_id = db.Column(
        db.Integer,
        db.ForeignKey("audit_exception_types.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    metrics = db.relationship(
        "AuditExceptionMetric",
        back_populates="exception_type",
        lazy="dynamic",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "label": self.label,
            "description": self.description,
            "sort_order": self.sort_order,
            "is_active": self.is_active,
            "is_hidden": self.is_hidden,
            "parent_id": self.parent_id,
        }

    def __repr__(self) -> str:
        return f"<AuditExceptionType {self.code}>"


class AuditExceptionMetric(db.Model):
    __tablename__ = "audit_exception_metrics"
    __table_args__ = (
        db.UniqueConstraint(
            "plaza_identifier",
            "exception_type_id",
            "year",
            "month",
            name="uq_audit_exception_metrics_plaza_type_period",
        ),
        db.CheckConstraint("month >= 1 AND month <= 12", name="ck_audit_exception_metrics_month"),
        db.CheckConstraint("year >= 1990 AND year <= 2100", name="ck_audit_exception_metrics_year"),
    )

    id = db.Column(db.BigInteger, primary_key=True)
    plaza_identifier = db.Column(
        db.String(36),
        db.ForeignKey("plazas.plaza_identifier", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exception_type_id = db.Column(
        db.Integer,
        db.ForeignKey("audit_exception_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    year = db.Column(db.SmallInteger, nullable=False)
    month = db.Column(db.SmallInteger, nullable=False)
    total_amount = db.Column(db.Numeric(18, 2), nullable=True)
    total_count = db.Column(db.Integer, nullable=True)
    # Set for percentage-only findings such as E11. Count and amount stay empty.
    percentage = db.Column(db.Numeric(8, 2), nullable=True)
    severity = db.Column(db.String(20), nullable=True)
    status = db.Column(db.String(20), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    exception_type = db.relationship(
        "AuditExceptionType",
        back_populates="metrics",
        foreign_keys=[exception_type_id],
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "plaza_identifier": self.plaza_identifier,
            "exception_type_id": self.exception_type_id,
            "year": self.year,
            "month": self.month,
            "total_amount": float(self.total_amount) if self.total_amount is not None else None,
            "total_count": int(self.total_count) if self.total_count is not None else None,
            "percentage": float(self.percentage) if self.percentage is not None else None,
            "severity": self.severity,
            "status": self.status,
            "notes": self.notes,
        }

    def __repr__(self) -> str:
        return (
            f"<AuditExceptionMetric plaza={self.plaza_identifier} "
            f"type={self.exception_type_id} {self.year}-{self.month:02d}>"
        )
