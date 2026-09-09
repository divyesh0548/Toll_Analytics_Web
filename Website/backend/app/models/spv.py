"""SPV / tollway master under a company."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.extensions import db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Spv(db.Model):
    __tablename__ = "spvs"

    id = db.Column(db.Integer, primary_key=True)
    spv_identifier = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    # One company can own many SPVs.
    company_identifier = db.Column(
        db.String(36),
        db.ForeignKey("companies.company_identifier", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    spv_name = db.Column(db.String(255), nullable=False)
    project_stretch_name = db.Column(db.String(255), nullable=True)
    nh_no = db.Column(db.String(50), nullable=True)
    chainage_from = db.Column(db.String(50), nullable=True)
    chainage_to = db.Column(db.String(50), nullable=True)
    length_km = db.Column(db.Integer, nullable=True)
    rate_notification_no_date = db.Column(db.String(255), nullable=True)
    annual_revision_pct = db.Column(db.Numeric(8, 2), nullable=True)
    wpi_linkage = db.Column(db.String(255), nullable=True)
    effective_from = db.Column(db.Date, nullable=True)
    rate_card_upload = db.Column(db.String(500), nullable=True)
    exempt_categories_policy = db.Column(db.Text, nullable=True)
    local_monthly_pass_rules = db.Column(db.Text, nullable=True)
    lead_bank_lender = db.Column(db.String(255), nullable=True)
    facility_limit = db.Column(db.String(255), nullable=True)
    escrow_bank = db.Column(db.String(255), nullable=True)
    revenue_share_premium_pct = db.Column(db.Numeric(8, 2), nullable=True)
    premium_escalation = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    company = db.relationship(
        "Company",
        back_populates="spvs",
        foreign_keys=[company_identifier],
        primaryjoin="Spv.company_identifier == Company.company_identifier",
    )

    def to_dict(self, *, include_company: bool = True) -> dict:
        payload = {
            "id": self.id,
            "spv_identifier": self.spv_identifier,
            "company_identifier": self.company_identifier,
            "spv_name": self.spv_name,
            "project_stretch_name": self.project_stretch_name,
            "nh_no": self.nh_no,
            "chainage_from": self.chainage_from,
            "chainage_to": self.chainage_to,
            "length_km": self.length_km,
            "rate_notification_no_date": self.rate_notification_no_date,
            "annual_revision_pct": (
                float(self.annual_revision_pct)
                if self.annual_revision_pct is not None
                else None
            ),
            "wpi_linkage": self.wpi_linkage,
            "effective_from": (
                self.effective_from.isoformat() if self.effective_from else None
            ),
            "rate_card_upload": self.rate_card_upload,
            "exempt_categories_policy": self.exempt_categories_policy,
            "local_monthly_pass_rules": self.local_monthly_pass_rules,
            "lead_bank_lender": self.lead_bank_lender,
            "facility_limit": self.facility_limit,
            "escrow_bank": self.escrow_bank,
            "revenue_share_premium_pct": (
                float(self.revenue_share_premium_pct)
                if self.revenue_share_premium_pct is not None
                else None
            ),
            "premium_escalation": self.premium_escalation,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_company and self.company is not None:
            payload["parent_company"] = {
                "company_identifier": self.company.company_identifier,
                "company_name": self.company.company_name,
                "short_code": self.company.short_code,
            }
        return payload

    def __repr__(self) -> str:
        return f"<Spv {self.spv_name}>"
