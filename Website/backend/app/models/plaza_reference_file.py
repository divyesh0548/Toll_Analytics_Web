"""Plaza rates and approved-exemption workbooks stored in S3."""

from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


REFERENCE_KINDS = ("rates", "approved_exemption")


class PlazaReferenceFile(db.Model):
    __tablename__ = "plaza_reference_files"
    __table_args__ = (
        db.CheckConstraint(
            "kind IN ('rates', 'approved_exemption')",
            name="ck_plaza_reference_files_kind",
        ),
        db.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_plaza_reference_files_dates",
        ),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    plaza_identifier = db.Column(
        db.String(36),
        db.ForeignKey("plazas.plaza_identifier", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = db.Column(db.String(32), nullable=False)
    valid_from = db.Column(db.Date, nullable=False)
    valid_to = db.Column(db.Date, nullable=True)
    s3_key = db.Column(db.Text, nullable=False)
    original_file_name = db.Column(db.String(255), nullable=False)
    file_size_bytes = db.Column(db.BigInteger, nullable=True)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utc_now
    )

    plaza = db.relationship("Plaza", foreign_keys=[plaza_identifier])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "plaza_identifier": self.plaza_identifier,
            "plaza_name": self.plaza.plaza_name if self.plaza else None,
            "kind": self.kind,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "original_file_name": self.original_file_name,
            "file_size_bytes": self.file_size_bytes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
