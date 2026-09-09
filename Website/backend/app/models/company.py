"""Company master record."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.extensions import db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    company_identifier = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    company_name = db.Column(db.String(255), nullable=False)
    short_code = db.Column(db.String(50), nullable=False, unique=True, index=True)
    cin = db.Column(db.String(50), nullable=True)
    pan = db.Column(db.String(20), nullable=True)
    gstin = db.Column(db.String(20), nullable=True)
    address = db.Column(db.Text, nullable=True)
    state = db.Column(db.String(100), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    pin = db.Column(db.String(20), nullable=True)
    holding_parent = db.Column(db.String(255), nullable=True)
    auditor = db.Column(db.String(255), nullable=True)
    financial_year_end = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    contacts = db.relationship(
        "CompanyContact",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="joined",
        foreign_keys="CompanyContact.company_identifier",
        primaryjoin="Company.company_identifier == CompanyContact.company_identifier",
    )
    spvs = db.relationship(
        "Spv",
        back_populates="company",
        lazy="select",
        foreign_keys="Spv.company_identifier",
        primaryjoin="Company.company_identifier == Spv.company_identifier",
    )

    def to_dict(self, *, include_contacts: bool = True) -> dict:
        payload = {
            "id": self.id,
            "company_identifier": self.company_identifier,
            "company_name": self.company_name,
            "short_code": self.short_code,
            "cin": self.cin,
            "pan": self.pan,
            "gstin": self.gstin,
            "address": self.address,
            "state": self.state,
            "city": self.city,
            "pin": self.pin,
            "holding_parent": self.holding_parent,
            "auditor": self.auditor,
            "financial_year_end": self.financial_year_end,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_contacts:
            payload["contacts"] = [c.to_dict() for c in self.contacts]
        return payload

    def __repr__(self) -> str:
        return f"<Company {self.short_code}>"
