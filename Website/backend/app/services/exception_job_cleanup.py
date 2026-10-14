"""Delete exception jobs older than N days (keep audit/pipeline output files)."""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.extensions import db
from app.models.audit_exception import AuditExceptionOutputFile
from app.models.exception_job import ExceptionJob, ExceptionJobFile
from app.models.exception_pipeline import (
    ExceptionPipelineBatch,
    ExceptionPipelineBatchStep,
    PipelineAuditExceptionOutputFile,
    PlazaMonthlyExceptionInput,
)
from app.services.exception_job_s3 import delete_keys

logger = logging.getLogger(__name__)

JOB_RETENTION_DAYS = 7

# Job-file slots kept on S3 when a job is deleted (outputs for reuse / audit).
_KEEP_JOB_FILE_SLOTS = frozenset({"output"})
_SCRAPE_MODE_PN_RE = re.compile(r"\|sm=(live|export)$", re.I)


def _protected_output_s3_keys() -> set[str]:
    """S3 keys that must never be deleted (audit / monthly / pipeline outputs)."""
    staging_keys = {
        row.s3_key
        for row in AuditExceptionOutputFile.query.filter_by(is_final_output=False).all()
        if row.s3_key
    }
    monthly_exempt_keys = {
        row.s3_key
        for row in PlazaMonthlyExceptionInput.query.filter_by(
            slot="full_exempt_final"
        ).all()
        if row.s3_key
    }
    final_output_keys = {
        row.s3_key
        for row in AuditExceptionOutputFile.query.filter_by(is_final_output=True).all()
        if row.s3_key
    }
    pipeline_output_keys = {
        row.s3_key
        for row in PipelineAuditExceptionOutputFile.query.all()
        if row.s3_key
    }
    return staging_keys | monthly_exempt_keys | final_output_keys | pipeline_output_keys


def _local_job_workspace(job: ExceptionJob) -> Path | None:
    """Resolve jobs/<process_name> for this program, if any."""
    from app.services.analytics_program_catalog import plaza_db_update_root
    from app.services.exception_program_catalog import (
        e4_program_root,
        e5_program_root,
        e6_program_root,
        e7_program_root,
        e9_program_root,
        e10_program_root,
        e11_program_root,
        e15_program_root,
        exempt_portal_root,
        valid_invalid_script_dir,
    )

    raw = str(job.process_name or "").strip()
    process_name = _SCRAPE_MODE_PN_RE.sub("", raw).rstrip("|").strip()
    if not process_name:
        return None

    code = str(job.program_code or "").strip().lower()
    roots: dict[str, Path] = {
        "e04": e4_program_root() / "jobs",
        "e05": e5_program_root() / "jobs",
        "e05_group": e5_program_root() / "jobs",
        "e06": e6_program_root() / "jobs",
        "e07": e7_program_root() / "jobs",
        "e09": e9_program_root() / "jobs",
        "e10": e10_program_root() / "jobs",
        "e11": e11_program_root() / "jobs",
        "e15": e15_program_root() / "jobs",
        "valid_invalid_lookup": valid_invalid_script_dir() / "jobs",
        "analytics_vrn_etc": plaza_db_update_root() / "jobs",
        "full_exempt_e1_e2_e3_e13_e14": (
            exempt_portal_root()
            / "File_Process"
            / "4_Full_Exempt_Pipeline"
        ),
    }
    jobs_root = roots.get(code)
    if jobs_root is None:
        return None
    candidate = jobs_root / process_name
    return candidate if candidate.is_dir() else None


def _purge_local_workspace(process_dir: Path) -> None:
    """
    Remove local job workspace inputs/temps.

    Keeps an `output/` subfolder (job result copies). Never touches sibling
    folders such as permit_cache / scrape caches (those are outside process_dir).
    """
    if not process_dir.is_dir():
        return
    output_dir = process_dir / "output"
    keep_output = output_dir.is_dir()
    for child in list(process_dir.iterdir()):
        if keep_output and child.resolve() == output_dir.resolve():
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove %s while deleting job workspace", child)
    # If output is empty after cleanup, drop the empty process folder.
    try:
        remaining = list(process_dir.iterdir())
        if not remaining:
            process_dir.rmdir()
        elif keep_output and remaining == [output_dir] and not any(output_dir.iterdir()):
            shutil.rmtree(process_dir, ignore_errors=True)
    except OSError:
        pass


def delete_exception_job(job: ExceptionJob) -> dict:
    """
    Delete one exception job and its input files.

    Keeps:
      - Audit / pipeline / monthly output S3 objects
      - Job files with slot=output
      - Shared web-scrape caches (permit_cache etc. — not under the job folder)
      - Local process_dir/output/

    Removes:
      - DB job (+ cascaded exception_job_files)
      - Other job S3 inputs (etc, vrn, permit, scrape_vehicles, …)
      - Local workspace inputs under jobs/<process_name>/
    """
    protected = _protected_output_s3_keys()
    file_rows = list(job.files or [])
    keys_to_delete = [
        f.s3_key
        for f in file_rows
        if f.s3_key
        and str(f.slot or "").strip().lower() not in _KEEP_JOB_FILE_SLOTS
        and f.s3_key not in protected
    ]

    job_uuid = job.job_uuid
    process_dir = _local_job_workspace(job)

    # Drop dangling pipeline references before deleting the job.
    steps = ExceptionPipelineBatchStep.query.filter_by(child_job_uuid=job_uuid).all()
    for step in steps:
        step.child_job_uuid = None
    batches = ExceptionPipelineBatch.query.filter_by(analytics_job_uuid=job_uuid).all()
    for batch in batches:
        batch.analytics_job_uuid = None

    db.session.delete(job)
    db.session.commit()

    if process_dir is not None:
        try:
            _purge_local_workspace(process_dir)
        except Exception:  # noqa: BLE001
            logger.exception("Failed purging local workspace for job %s", job_uuid)

    deleted_s3 = 0
    if keys_to_delete:
        try:
            delete_keys(keys_to_delete)
            deleted_s3 = len(keys_to_delete)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Deleted job %s but failed removing some S3 input keys", job_uuid
            )

    logger.info(
        "Deleted exception job %s (s3_inputs=%s, local=%s)",
        job_uuid,
        deleted_s3,
        str(process_dir) if process_dir else "none",
    )
    return {
        "job_uuid": job_uuid,
        "deleted_s3_keys": deleted_s3,
        "local_workspace_purged": process_dir is not None,
    }


def cleanup_expired_exception_jobs(*, retention_days: int = JOB_RETENTION_DAYS) -> int:
    """
    Remove exception_jobs (any status) older than retention_days.

    - Deletes DB job rows (cascades exception_job_files).
    - Deletes job input objects from S3 when safe.
    - Does NOT delete audit_exception_output_files / pipeline output files.
    - Clears pipeline batch/step UUID pointers that referenced removed jobs.

    Returns number of jobs deleted.
    """
    days = max(1, int(retention_days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    jobs = (
        ExceptionJob.query.filter(ExceptionJob.created_at < cutoff)
        .order_by(ExceptionJob.id.asc())
        .all()
    )
    if not jobs:
        return 0

    job_ids = [j.id for j in jobs]
    job_uuids = {j.job_uuid for j in jobs if j.job_uuid}

    # Inputs only — never touch registered exception outputs.
    staging_keys = {
        row.s3_key
        for row in AuditExceptionOutputFile.query.filter_by(is_final_output=False).all()
        if row.s3_key
    }
    monthly_exempt_keys = {
        row.s3_key
        for row in PlazaMonthlyExceptionInput.query.filter_by(
            slot="full_exempt_final"
        ).all()
        if row.s3_key
    }
    # Final monthly outputs must stay downloadable from the audit panel.
    final_output_keys = {
        row.s3_key
        for row in AuditExceptionOutputFile.query.filter_by(is_final_output=True).all()
        if row.s3_key
    }
    pipeline_output_keys = {
        row.s3_key
        for row in PipelineAuditExceptionOutputFile.query.all()
        if row.s3_key
    }
    protected = (
        staging_keys | monthly_exempt_keys | final_output_keys | pipeline_output_keys
    )

    file_rows = (
        ExceptionJobFile.query.filter(ExceptionJobFile.job_id.in_(job_ids)).all()
        if job_ids
        else []
    )
    keys = [
        f.s3_key
        for f in file_rows
        if f.s3_key and f.s3_key not in protected
    ]

    # Drop dangling pipeline references before deleting jobs.
    if job_uuids:
        steps = (
            ExceptionPipelineBatchStep.query.filter(
                ExceptionPipelineBatchStep.child_job_uuid.in_(job_uuids)
            ).all()
        )
        for step in steps:
            step.child_job_uuid = None

        batches = (
            ExceptionPipelineBatch.query.filter(
                ExceptionPipelineBatch.analytics_job_uuid.in_(job_uuids)
            ).all()
        )
        for batch in batches:
            batch.analytics_job_uuid = None

    for job in jobs:
        db.session.delete(job)

    try:
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        logger.exception("Failed to delete expired exception jobs")
        raise

    if keys:
        try:
            delete_keys(keys)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Deleted %s expired job(s) but failed removing some S3 input keys",
                len(jobs),
            )

    logger.info(
        "Cleaned %s exception job(s) older than %s days (outputs kept)",
        len(jobs),
        days,
    )
    return len(jobs)
