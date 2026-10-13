"""Monthly plaza inputs and one-click exception pipeline batch runs.

Parallel to legacy exception_jobs / audit_exception_metrics — does not replace them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.extensions import db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


class PlazaMonthlyExceptionInput(db.Model):
    """User-uploaded (or pipeline-produced) source file for a plaza + month."""

    __tablename__ = "plaza_monthly_exception_inputs"
    __table_args__ = (
        db.CheckConstraint("month >= 1 AND month <= 12", name="ck_plaza_monthly_exc_inputs_month"),
        db.CheckConstraint("year >= 1990 AND year <= 2100", name="ck_plaza_monthly_exc_inputs_year"),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    plaza_identifier = db.Column(
        db.String(36),
        db.ForeignKey("plazas.plaza_identifier", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year = db.Column(db.SmallInteger, nullable=False)
    month = db.Column(db.SmallInteger, nullable=False)
    # Logical slot: vrn, etc, pass, concessionaire, scraped, to_plaza_vrn, full_exempt_final, …
    slot = db.Column(db.String(64), nullable=False, index=True)
    original_file_name = db.Column(db.String(512), nullable=False)
    s3_key = db.Column(db.String(1024), nullable=False)
    file_url = db.Column(db.String(2048), nullable=False)
    file_size_bytes = db.Column(db.BigInteger, nullable=True)
    content_type = db.Column(db.String(128), nullable=True)
    # upload | pipeline_output
    source = db.Column(db.String(32), nullable=False, default="upload")
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
            "year": self.year,
            "month": self.month,
            "slot": self.slot,
            "original_file_name": self.original_file_name,
            "s3_key": self.s3_key,
            "file_url": self.file_url,
            "file_size_bytes": (
                int(self.file_size_bytes) if self.file_size_bytes is not None else None
            ),
            "content_type": self.content_type,
            "source": self.source,
            "created_at": _iso_utc(self.created_at),
        }


class ExceptionPipelineBatch(db.Model):
    __tablename__ = "exception_pipeline_batches"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    batch_uuid = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    plaza_identifier = db.Column(
        db.String(36),
        db.ForeignKey("plazas.plaza_identifier", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    pipeline_plaza_key = db.Column(db.String(100), nullable=True)
    year = db.Column(db.SmallInteger, nullable=False)
    month = db.Column(db.SmallInteger, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="draft", index=True)
    progress_message = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    continue_on_failure = db.Column(db.Boolean, nullable=False, default=True)
    # Parallel plaza ETL (VRN/ETC analytics) — not part of the serial exception chain.
    analytics_job_uuid = db.Column(db.String(36), nullable=True, index=True)
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

    steps = db.relationship(
        "ExceptionPipelineBatchStep",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="ExceptionPipelineBatchStep.sort_order",
    )
    plaza = db.relationship("Plaza", foreign_keys=[plaza_identifier])

    def to_dict(self, *, include_steps: bool = True) -> dict:
        payload = {
            "batch_uuid": self.batch_uuid,
            "plaza_identifier": self.plaza_identifier,
            "plaza_name": self.plaza.plaza_name if self.plaza else None,
            "pipeline_plaza_key": self.pipeline_plaza_key,
            "year": self.year,
            "month": self.month,
            "status": self.status,
            "progress_message": self.progress_message,
            "error_message": self.error_message,
            "continue_on_failure": bool(self.continue_on_failure),
            "analytics_job_uuid": self.analytics_job_uuid,
            "started_at": _iso_utc(self.started_at),
            "finished_at": _iso_utc(self.finished_at),
            "created_at": _iso_utc(self.created_at),
        }
        if include_steps:
            payload["steps"] = [s.to_dict() for s in self.steps]
        if self.analytics_job_uuid:
            from app.models.exception_job import ExceptionJob

            analytics_job = ExceptionJob.query.filter_by(
                job_uuid=self.analytics_job_uuid
            ).first()
            if analytics_job is not None:
                payload["analytics"] = {
                    "job_uuid": analytics_job.job_uuid,
                    "program_code": analytics_job.program_code,
                    "label": "Plaza analytics (VRN / ETC)",
                    "status": analytics_job.status,
                    "progress_message": analytics_job.progress_message,
                    "error_message": analytics_job.error_message,
                    "started_at": _iso_utc(analytics_job.started_at),
                    "finished_at": _iso_utc(analytics_job.finished_at),
                }
            else:
                payload["analytics"] = {
                    "job_uuid": self.analytics_job_uuid,
                    "program_code": "analytics_vrn_etc",
                    "label": "Plaza analytics (VRN / ETC)",
                    "status": "unknown",
                    "progress_message": None,
                    "error_message": None,
                }
        else:
            payload["analytics"] = None
        return payload


class ExceptionPipelineBatchStep(db.Model):
    __tablename__ = "exception_pipeline_batch_steps"
    __table_args__ = (
        db.UniqueConstraint("batch_id", "program_code", name="uq_pipeline_batch_steps_program"),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    batch_id = db.Column(
        db.BigInteger,
        db.ForeignKey("exception_pipeline_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    program_code = db.Column(db.String(64), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(32), nullable=False, default="pending", index=True)
    child_job_uuid = db.Column(db.String(36), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    batch = db.relationship("ExceptionPipelineBatch", back_populates="steps")

    def to_dict(self) -> dict:
        status = self.status
        error_message = self.error_message
        started_at = self.started_at
        finished_at = self.finished_at
        # Mirror live child-job status so UI shows "running" while the worker
        # is executing (step row is only set to queued until the job finishes).
        if self.child_job_uuid:
            from app.models.exception_job import ExceptionJob

            child = ExceptionJob.query.filter_by(
                job_uuid=self.child_job_uuid
            ).first()
            if child is not None:
                child_status = str(child.status or "").strip()
                if child_status:
                    status = child_status
                if child.error_message and not error_message:
                    error_message = child.error_message
                if child.started_at is not None:
                    started_at = child.started_at
                if child.finished_at is not None:
                    finished_at = child.finished_at
        return {
            "program_code": self.program_code,
            "sort_order": self.sort_order,
            "status": status,
            "child_job_uuid": self.child_job_uuid,
            "error_message": error_message,
            "started_at": _iso_utc(started_at),
            "finished_at": _iso_utc(finished_at),
        }


class PipelineAuditExceptionMetric(db.Model):
    """One-click pipeline metrics — parallel to audit_exception_metrics."""

    __tablename__ = "pipeline_audit_exception_metrics"
    __table_args__ = (
        db.UniqueConstraint(
            "plaza_identifier",
            "exception_type_id",
            "year",
            "month",
            name="uq_pipeline_audit_exception_metrics_plaza_type_period",
        ),
        db.CheckConstraint("month >= 1 AND month <= 12", name="ck_pipeline_aem_month"),
        db.CheckConstraint("year >= 1990 AND year <= 2100", name="ck_pipeline_aem_year"),
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
            "source": "pipeline",
        }


class PipelineAuditExceptionOutputFile(db.Model):
    """One-click pipeline output files — parallel to audit_exception_output_files."""

    __tablename__ = "pipeline_audit_exception_output_files"

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
    month_label = db.Column(db.String(64), nullable=False)
    file_name = db.Column(db.String(512), nullable=False)
    s3_key = db.Column(db.String(1024), nullable=False)
    file_url = db.Column(db.String(2048), nullable=False)
    original_file_name = db.Column(db.String(512), nullable=True)
    file_size_bytes = db.Column(db.BigInteger, nullable=True)
    is_final_output = db.Column(db.Boolean, nullable=False, default=True)
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
            "exception_type_id": self.exception_type_id,
            "month_label": self.month_label,
            "file_name": self.file_name,
            "s3_key": self.s3_key,
            "file_url": self.file_url,
            "original_file_name": self.original_file_name,
            "file_size_bytes": (
                int(self.file_size_bytes) if self.file_size_bytes is not None else None
            ),
            "is_final_output": bool(self.is_final_output),
            "created_at": _iso_utc(self.created_at),
            "source": "pipeline",
        }
