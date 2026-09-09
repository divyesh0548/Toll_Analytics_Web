"""Company contact persons."""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CompanyContact(db.Model):
    __tablename__ = "company_contacts"

    id = db.Column(db.Integer, primary_key=True)
    company_identifier = db.Column(
        db.String(36),
        db.ForeignKey("companies.company_identifier", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    company = db.relationship(
        "Company",
        back_populates="contacts",
        foreign_keys=[company_identifier],
        primaryjoin="CompanyContact.company_identifier == Company.company_identifier",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "company_identifier": self.company_identifier,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<CompanyContact {self.name}>"
