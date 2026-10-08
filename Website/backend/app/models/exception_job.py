"""Exception processing jobs (upload inputs → run pipeline → metrics)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.extensions import db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


JOB_STATUSES = (
    "draft",
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)


class ExceptionJob(db.Model):
    __tablename__ = "exception_jobs"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    job_uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    # Catalog key, e.g. full_exempt_e1_e2_e3_e13_e14
    program_code = db.Column(db.String(64), nullable=False, index=True)
    plaza_identifier = db.Column(
        db.String(36),
        db.ForeignKey("plazas.plaza_identifier", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Key expected by Full Exempt codes_dump / annexure config (e.g. BASSI)
    pipeline_plaza_key = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="draft", index=True)
    progress_message = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    # Local process folder name under the exempt portal File_Process tree
    process_name = db.Column(db.String(255), nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    files = db.relationship(
        "ExceptionJobFile",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="ExceptionJobFile.id",
    )
    plaza = db.relationship("Plaza", foreign_keys=[plaza_identifier])

    def to_dict(self, *, include_files: bool = True) -> dict:
        payload = {
            "id": self.id,
            "job_uuid": self.job_uuid,
            "program_code": self.program_code,
            "plaza_identifier": self.plaza_identifier,
            "pipeline_plaza_key": self.pipeline_plaza_key,
            "status": self.status,
            "progress_message": self.progress_message,
            "error_message": self.error_message,
            "process_name": self.process_name,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "plaza_name": self.plaza.plaza_name if self.plaza else None,
        }
        if include_files:
            payload["files"] = [f.to_dict() for f in self.files]
        return payload


class ExceptionJobFile(db.Model):
    __tablename__ = "exception_job_files"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    job_id = db.Column(
        db.BigInteger,
        db.ForeignKey("exception_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # e.g. lc_etc, vrn, pass, concessionaire, rates, approved_exemption
    slot = db.Column(db.String(64), nullable=False, index=True)
    original_file_name = db.Column(db.String(512), nullable=False)
    s3_key = db.Column(db.String(1024), nullable=False)
    file_url = db.Column(db.String(2048), nullable=True)
    file_size_bytes = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)

    job = db.relationship("ExceptionJob", back_populates="files")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "slot": self.slot,
            "original_file_name": self.original_file_name,
            "s3_key": self.s3_key,
            "file_url": self.file_url,
            "file_size_bytes": (
                int(self.file_size_bytes) if self.file_size_bytes is not None else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
