"""Delete exception jobs older than N days (keep audit/pipeline output files)."""

from __future__ import annotations

import json
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
# File Upload stores one month of inputs. Nothing in that store lives longer.
MONTHLY_INPUT_RETENTION_DAYS = 31
RETENTION_FILE_NAME = "job_retention.json"
# Website-created run folders only. Manual process folders stay.
_WEBSITE_JOB_DIR_RE = re.compile(
    r"^(?:w|e4|e5|e6|e7|e9|e10|e11|e15|vil|an)_[0-9a-f]{8}_[0-9a-f]{6}$",
    re.I,
)

# Job-file slots kept on S3 when a job is deleted (outputs for reuse / audit).
_KEEP_JOB_FILE_SLOTS = frozenset({"output"})
_SCRAPE_MODE_PN_RE = re.compile(r"\|sm=(live|export)$", re.I)


def _protected_output_s3_keys() -> set[str]:
    """S3 keys that must never be deleted (audit / monthly inputs / pipeline outputs)."""
    staging_keys = {
        row.s3_key
        for row in AuditExceptionOutputFile.query.filter_by(is_final_output=False).all()
        if row.s3_key
    }
    # All monthly File Upload inputs (vrn/etc/pass/… + full_exempt_final).
    # Pipeline jobs copy these same keys onto ExceptionJobFile; deleting a job
    # must not wipe the shared monthly objects the period UI still references.
    monthly_input_keys = {
        row.s3_key
        for row in PlazaMonthlyExceptionInput.query.all()
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
    return staging_keys | monthly_input_keys | final_output_keys | pipeline_output_keys


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
    }
    if code == "full_exempt_e1_e2_e3_e13_e14":
        for jobs_root in (
            exempt_portal_root()
            / "File_Process"
            / "Exempt_Query"
            / "4_Full_Exempt_Pipeline",
            exempt_portal_root()
            / "File_Process"
            / "4_Full_Exempt_Pipeline",
        ):
            candidate = jobs_root / process_name
            if candidate.is_dir():
                return candidate
        return None
    jobs_root = roots.get(code)
    if jobs_root is None:
        return None
    candidate = jobs_root / process_name
    return candidate if candidate.is_dir() else None


def list_local_job_outputs(job: ExceptionJob) -> list[dict]:
    """Generated files under the job's output folder (not inputs)."""
    root = _local_job_workspace(job)
    if root is None:
        return []
    output_dir = root / "output"
    if not output_dir.is_dir():
        return []
    files: list[dict] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("~$"):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            size = None
        files.append(
            {
                "name": path.name,
                "relative_path": relative,
                "file_size_bytes": size,
            }
        )
    return files


def resolve_local_job_output(job: ExceptionJob, relative_path: str) -> Path:
    """Resolve a download path that must stay inside the job output folder."""
    root = _local_job_workspace(job)
    if root is None:
        raise FileNotFoundError("Job output folder is not on the server.")
    raw = str(relative_path or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or ".." in Path(raw).parts:
        raise PermissionError("Invalid output path.")
    relative = Path(raw)
    if not relative.parts or relative.parts[0] != "output":
        raise PermissionError("Only generated output files can be downloaded.")
    path = (root / relative).resolve()
    output_root = (root / "output").resolve()
    if output_root != path and output_root not in path.parents:
        raise PermissionError("Invalid output path.")
    if not path.is_file():
        raise FileNotFoundError("Output file not found.")
    return path


def _purge_local_workspace(process_dir: Path) -> None:
    """
    Remove local job workspace inputs/temps.

    Keeps an `output/` subfolder (job result copies). Never touches sibling
    folders outside process_dir. Permit rows live in permit_scrape_cache.
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
      - permit_scrape_cache rows (shared permit table, not a job file)
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

    # Inputs only — never touch registered monthly inputs / exception outputs.
    protected = _protected_output_s3_keys()

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


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def write_job_retention_stamp(process_dir: Path) -> None:
    """Record when a successful local job folder may be deleted."""
    folder = Path(process_dir)
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "delete_after_days": JOB_RETENTION_DAYS,
    }
    (folder / RETENTION_FILE_NAME).write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def delete_local_job_inputs(process_dir: Path) -> None:
    """Drop local input copies. Keep output/ and the retention stamp."""
    folder = Path(process_dir)
    if not folder.is_dir():
        return
    keep = {"output", RETENTION_FILE_NAME}
    for child in list(folder.iterdir()):
        if child.name in keep:
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError:
            logger.warning("Could not delete local input %s", child, exc_info=True)


def _finished_at_from_stamp(path: Path) -> datetime | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = str((data or {}).get("finished_at") or "").strip()
    if not raw:
        return None
    try:
        return _as_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None


def _local_job_parent_dirs() -> list[Path]:
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

    return [
        e4_program_root() / "jobs",
        e5_program_root() / "jobs",
        e6_program_root() / "jobs",
        e7_program_root() / "jobs",
        e9_program_root() / "jobs",
        e10_program_root() / "jobs",
        e11_program_root() / "jobs",
        e15_program_root() / "jobs",
        valid_invalid_script_dir() / "jobs",
        plaza_db_update_root() / "jobs",
        exempt_portal_root()
        / "File_Process"
        / "Exempt_Query"
        / "4_Full_Exempt_Pipeline",
        exempt_portal_root() / "File_Process" / "4_Full_Exempt_Pipeline",
    ]


def _active_local_process_names() -> set[str]:
    names: set[str] = set()
    rows = ExceptionJob.query.filter(
        ExceptionJob.status.in_(("queued", "running"))
    ).all()
    for job in rows:
        raw = _SCRAPE_MODE_PN_RE.sub("", str(job.process_name or "")).rstrip("|").strip()
        if raw:
            names.add(raw)
    return names


def cleanup_expired_local_job_folders(days: int = JOB_RETENTION_DAYS) -> int:
    """Delete local job folders 7 days after they finished, including output."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        active = _active_local_process_names()
    except Exception:  # noqa: BLE001
        logger.exception("Could not load running jobs; skipping local folder cleanup")
        return 0

    removed = 0
    for parent in _local_job_parent_dirs():
        if not parent.is_dir():
            continue
        for child in list(parent.iterdir()):
            if (
                not child.is_dir()
                or child.name in active
                or _WEBSITE_JOB_DIR_RE.match(child.name) is None
            ):
                continue
            stamp = child / RETENTION_FILE_NAME
            finished = _finished_at_from_stamp(stamp) if stamp.is_file() else None
            if finished is not None:
                expired = finished <= cutoff
            else:
                try:
                    expired = child.stat().st_mtime <= cutoff.timestamp()
                except OSError:
                    continue
            if not expired:
                continue
            shutil.rmtree(child, ignore_errors=True)
            if not child.exists():
                removed += 1
                logger.info(
                    "Removed local job folder older than %s days: %s", days, child
                )
    return removed


def cleanup_expired_monthly_inputs(
    days: int = MONTHLY_INPUT_RETENTION_DAYS,
) -> int:
    """Delete File Upload inputs older than one month. Output files stay."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = PlazaMonthlyExceptionInput.query.all()
    expired: list[PlazaMonthlyExceptionInput] = []
    kept_keys: set[str] = set()
    for row in rows:
        created = row.created_at
        if created is not None and _as_utc(created) > cutoff:
            if row.s3_key:
                kept_keys.add(row.s3_key)
            continue
        expired.append(row)
    if not expired:
        return 0

    output_keys = {
        row.s3_key
        for row in AuditExceptionOutputFile.query.filter_by(is_final_output=True).all()
        if row.s3_key
    }
    output_keys.update(
        row.s3_key
        for row in PipelineAuditExceptionOutputFile.query.all()
        if row.s3_key
    )
    keys: list[str] = []
    seen: set[str] = set()
    for row in expired:
        key = row.s3_key or ""
        # The exempt workbook E15 reads is a monthly input, not a kept result.
        # Delete that S3 object with the other month-old inputs.
        spare_outputs = row.slot != "full_exempt_final"
        if (
            key
            and key not in kept_keys
            and key not in seen
            and (not spare_outputs or key not in output_keys)
        ):
            seen.add(key)
            keys.append(key)
        db.session.delete(row)

    try:
        if keys:
            delete_keys(keys)
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        logger.exception("Failed to delete monthly inputs older than %s days", days)
        raise

    logger.info(
        "Removed %s monthly input record(s) older than %s days",
        len(expired),
        days,
    )
    return len(expired)
