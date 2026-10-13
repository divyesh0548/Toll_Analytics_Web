"""Create/start monthly exception pipeline batches without changing single-run jobs."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.extensions import db
from app.models.exception_job import ExceptionJob, ExceptionJobFile
from app.models.exception_pipeline import (
    ExceptionPipelineBatch,
    ExceptionPipelineBatchStep,
    PlazaMonthlyExceptionInput,
)
from app.models.plaza import Plaza
from app.services.analytics_program_catalog import ANALYTICS_VRN_ETC_PROGRAM
from app.services.exception_program_catalog import resolve_pipeline_plaza_key
from app.services.pipeline_dependency_catalog import (
    PIPELINE_METRICS_TABLE,
    PIPELINE_OUTPUT_FILES_TABLE,
    evaluate_program_availability,
    get_pipeline_program,
)

ANALYTICS_PROGRAM_CODE = ANALYTICS_VRN_ETC_PROGRAM["code"]
ANALYTICS_SLOT_MAP = {"vrn": "vrn", "etc": "etc"}

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def present_slots_for_period(plaza_identifier: str, year: int, month: int) -> set[str]:
    rows = (
        PlazaMonthlyExceptionInput.query.filter_by(
            plaza_identifier=plaza_identifier,
            year=int(year),
            month=int(month),
        )
        .with_entities(PlazaMonthlyExceptionInput.slot)
        .distinct()
        .all()
    )
    return {str(r[0]) for r in rows if r and r[0]}


def period_status(plaza_identifier: str, year: int, month: int) -> dict:
    present = present_slots_for_period(plaza_identifier, year, month)
    files = (
        PlazaMonthlyExceptionInput.query.filter_by(
            plaza_identifier=plaza_identifier,
            year=int(year),
            month=int(month),
        )
        .order_by(PlazaMonthlyExceptionInput.slot, PlazaMonthlyExceptionInput.id)
        .all()
    )
    analytics_ready = bool(present & {"vrn", "etc"})
    return {
        "plaza_identifier": plaza_identifier,
        "year": int(year),
        "month": int(month),
        "present_slots": sorted(present),
        "files": [f.to_dict() for f in files],
        "programs": evaluate_program_availability(present),
        "analytics_ready": analytics_ready,
        "analytics_label": ANALYTICS_VRN_ETC_PROGRAM.get("label")
        or "Plaza analytics (VRN / ETC)",
    }


def create_batch(
    *,
    plaza_identifier: str,
    year: int,
    month: int,
    program_codes: list[str],
    pipeline_plaza_key: str | None = None,
    continue_on_failure: bool = True,
    run_analytics: bool = True,
    created_by_user_id: int | None = None,
) -> ExceptionPipelineBatch:
    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first()
    if plaza is None:
        raise ValueError(f"Unknown plaza_identifier: {plaza_identifier}")

    resolved_key = str(pipeline_plaza_key or "").strip().upper() or None
    if not resolved_key:
        resolved_key = resolve_pipeline_plaza_key(plaza_identifier)
    pipeline_plaza_key = resolved_key

    present = present_slots_for_period(plaza_identifier, year, month)
    availability = {
        p["code"]: p for p in evaluate_program_availability(present)
    }

    selected: list[dict] = []
    for code in program_codes:
        program = get_pipeline_program(code)
        if program is None:
            raise ValueError(f"Unknown program_code: {code}")
        info = availability.get(code) or {}
        if not info.get("enabled"):
            missing = ", ".join(info.get("missing_slots") or [])
            raise ValueError(
                f"Program {code} is not enabled for this period "
                f"(missing slots: {missing or 'unknown'})."
            )
        if program.get("requires_pipeline_plaza_key") and not str(
            pipeline_plaza_key or ""
        ).strip():
            raise ValueError(
                f"No Full Exempt plaza key mapped for this plaza. "
                f"Set plaza_identifiers in annexure_plaza_config.json "
                f"(required for {code})."
            )
        selected.append(program)

    analytics_ready = bool(present & {"vrn", "etc"})
    if not selected and not (run_analytics and analytics_ready):
        raise ValueError(
            "Select at least one exception program, or enable plaza analytics "
            "with VRN/ETC uploaded."
        )

    selected.sort(key=lambda p: int(p.get("sort_order") or 0))

    batch = ExceptionPipelineBatch(
        batch_uuid=str(uuid.uuid4()),
        plaza_identifier=plaza_identifier,
        pipeline_plaza_key=str(pipeline_plaza_key or "").strip() or None,
        year=int(year),
        month=int(month),
        status="draft",
        continue_on_failure=bool(continue_on_failure),
        created_by_user_id=created_by_user_id,
        progress_message="Draft — not started",
    )
    db.session.add(batch)
    db.session.flush()

    for order, program in enumerate(selected):
        db.session.add(
            ExceptionPipelineBatchStep(
                batch_id=batch.id,
                program_code=program["code"],
                sort_order=order,
                status="pending",
            )
        )
    db.session.commit()
    return batch


def _attach_monthly_files_to_job(
    job: ExceptionJob,
    *,
    plaza_identifier: str,
    year: int,
    month: int,
    program: dict,
) -> None:
    slot_map: dict[str, str] = dict(program.get("slot_map") or {})
    for monthly_slot, job_slot in slot_map.items():
        inputs = PlazaMonthlyExceptionInput.query.filter_by(
            plaza_identifier=plaza_identifier,
            year=int(year),
            month=int(month),
            slot=monthly_slot,
        ).all()
        for row in inputs:
            db.session.add(
                ExceptionJobFile(
                    job_id=job.id,
                    slot=job_slot,
                    original_file_name=row.original_file_name,
                    s3_key=row.s3_key,
                    file_url=row.file_url,
                    file_size_bytes=row.file_size_bytes,
                )
            )


def enqueue_analytics_track(batch: ExceptionPipelineBatch) -> ExceptionJob | None:
    """
    Queue plaza VRN/ETC analytics in parallel with the exception chain.
    Uses the same monthly vrn/etc inputs. Does not write pipeline_* tables.
    """
    present = present_slots_for_period(batch.plaza_identifier, batch.year, batch.month)
    if not (present & {"vrn", "etc"}):
        batch.analytics_job_uuid = None
        return None

    pipeline_key = batch.pipeline_plaza_key or (
        batch.plaza.plaza_name if batch.plaza else None
    ) or "PLAZA"
    job = ExceptionJob(
        job_uuid=str(uuid.uuid4()),
        program_code=ANALYTICS_PROGRAM_CODE,
        plaza_identifier=batch.plaza_identifier,
        pipeline_plaza_key=str(pipeline_key).strip().upper(),
        status="queued",
        progress_message=(
            f"Pipeline analytics (parallel) · batch {batch.batch_uuid[:8]}…"
        ),
        created_by_user_id=batch.created_by_user_id,
    )
    db.session.add(job)
    db.session.flush()
    _attach_monthly_files_to_job(
        job,
        plaza_identifier=batch.plaza_identifier,
        year=batch.year,
        month=batch.month,
        program={"slot_map": ANALYTICS_SLOT_MAP},
    )
    batch.analytics_job_uuid = job.job_uuid
    if batch.started_at is None:
        batch.started_at = _utc_now()
    if batch.status == "draft":
        batch.status = "running"
    batch.progress_message = (
        (batch.progress_message or "") + " · Plaza analytics queued"
    ).strip(" ·")
    db.session.commit()
    logger.info(
        "Queued parallel analytics job %s for batch %s",
        job.job_uuid,
        batch.batch_uuid,
    )
    return job


def is_pipeline_analytics_job(job_uuid: str) -> bool:
    """True when this job is the parallel analytics track of a pipeline batch."""
    uuid_s = str(job_uuid or "").strip()
    if not uuid_s:
        return False
    return (
        ExceptionPipelineBatch.query.filter_by(analytics_job_uuid=uuid_s).first()
        is not None
    )


def enqueue_next_pipeline_step(batch: ExceptionPipelineBatch) -> ExceptionJob | None:
    """Queue the next pending step as a normal ExceptionJob (pipeline env later)."""
    if str(batch.status or "") == "cancelled":
        return None
    step = (
        ExceptionPipelineBatchStep.query.filter_by(batch_id=batch.id, status="pending")
        .order_by(ExceptionPipelineBatchStep.sort_order.asc())
        .first()
    )
    if step is None:
        if str(batch.status or "") == "cancelled":
            return None
        batch.status = "succeeded"
        batch.progress_message = "All selected exception programs finished."
        batch.finished_at = _utc_now()
        db.session.commit()
        return None

    program = get_pipeline_program(step.program_code)
    if program is None:
        step.status = "failed"
        step.error_message = f"Unknown program {step.program_code}"
        step.finished_at = _utc_now()
        db.session.commit()
        return enqueue_next_pipeline_step(batch)

    # Re-check deps (Full Exempt may have just produced full_exempt_final).
    present = present_slots_for_period(batch.plaza_identifier, batch.year, batch.month)
    if not set(program.get("required_slots") or []).issubset(present):
        missing = [
            s for s in (program.get("required_slots") or []) if s not in present
        ]
        step.status = "failed"
        step.error_message = f"Missing required slots: {', '.join(missing)}"
        step.finished_at = _utc_now()
        if not batch.continue_on_failure:
            batch.status = "failed"
            batch.error_message = step.error_message
            batch.finished_at = _utc_now()
            db.session.commit()
            return None
        db.session.commit()
        return enqueue_next_pipeline_step(batch)

    pipeline_key = batch.pipeline_plaza_key or batch.plaza.plaza_name or "PLAZA"
    job = ExceptionJob(
        job_uuid=str(uuid.uuid4()),
        program_code=step.program_code,
        plaza_identifier=batch.plaza_identifier,
        pipeline_plaza_key=str(pipeline_key).strip().upper(),
        status="queued",
        progress_message=f"Pipeline batch {batch.batch_uuid[:8]}…",
        created_by_user_id=batch.created_by_user_id,
    )
    db.session.add(job)
    db.session.flush()
    _attach_monthly_files_to_job(
        job,
        plaza_identifier=batch.plaza_identifier,
        year=batch.year,
        month=batch.month,
        program=program,
    )
    step.status = "queued"
    step.child_job_uuid = job.job_uuid
    step.started_at = _utc_now()
    batch.status = "running"
    batch.progress_message = f"Queued {program.get('label') or step.program_code}"
    if batch.started_at is None:
        batch.started_at = _utc_now()
    db.session.commit()
    return job


def start_batch(
    batch_uuid: str,
    *,
    run_analytics: bool = True,
) -> ExceptionPipelineBatch:
    batch = ExceptionPipelineBatch.query.filter_by(batch_uuid=batch_uuid).first()
    if batch is None:
        raise ValueError("Batch not found")
    if batch.status not in {"draft", "failed"}:
        raise ValueError(f"Cannot start batch in status {batch.status}")
    if batch.status == "failed":
        # Reset pending/failed steps that have no finished success.
        for step in batch.steps:
            if step.status in {"failed", "pending"} and step.status != "succeeded":
                if step.status == "failed":
                    step.status = "pending"
                    step.error_message = None
                    step.child_job_uuid = None
                    step.started_at = None
                    step.finished_at = None
        batch.error_message = None
        batch.finished_at = None
        batch.analytics_job_uuid = None

    # Free worker slots: stop any earlier active run for the same plaza/month.
    supersede_active_batches_for_period(
        plaza_identifier=batch.plaza_identifier,
        year=int(batch.year),
        month=int(batch.month),
        keep_batch_uuid=batch.batch_uuid,
    )

    # Parallel track: plaza analytics from the same VRN/ETC monthly files.
    if run_analytics:
        enqueue_analytics_track(batch)
        db.session.refresh(batch)
    else:
        batch.analytics_job_uuid = None
        db.session.commit()

    pending = (
        ExceptionPipelineBatchStep.query.filter_by(batch_id=batch.id, status="pending")
        .count()
    )
    if pending:
        enqueue_next_pipeline_step(batch)
    elif batch.analytics_job_uuid:
        batch.status = "running"
        batch.progress_message = "Plaza analytics running (no exception programs selected)."
        if batch.started_at is None:
            batch.started_at = _utc_now()
        db.session.commit()
    else:
        raise ValueError(
            "Nothing to run — select exception checks and/or enable plaza analytics "
            "with VRN/ETC uploaded."
        )

    db.session.refresh(batch)
    return batch


def find_batch_step_for_job(job_uuid: str) -> ExceptionPipelineBatchStep | None:
    return ExceptionPipelineBatchStep.query.filter_by(child_job_uuid=job_uuid).first()


# Env keys that must point at pipeline_* tables for File Upload child jobs.
# Include Plaza_analytics_Table_NAME — E4/E6/E15 prefer it over Exception_Metrics_Table.
_PIPELINE_TABLE_ENV_KEYS = (
    "Exception_Metrics_Table",
    "EXCEPTION_METRICS_TABLE",
    "Plaza_analytics_Table_NAME",
    "PLAZA_ANALYTICS_TABLE_NAME",
    "EXCEPTION_OUTPUT_FILES_TABLE",
    "Exception_Output_Files_Table",
    "PIPELINE_BATCH_MODE",
)


def apply_pipeline_env_for_job(job: ExceptionJob) -> bool:
    """
    If this job belongs to a pipeline batch, point metrics/output writers
    at the parallel pipeline_* tables. Returns True when applied.
    """
    import os

    step = find_batch_step_for_job(job.job_uuid)
    if step is None:
        return False
    os.environ["Exception_Metrics_Table"] = PIPELINE_METRICS_TABLE
    os.environ["EXCEPTION_METRICS_TABLE"] = PIPELINE_METRICS_TABLE
    # E4/E6/E15 resolve metrics table via Plaza_analytics_Table_NAME first.
    os.environ["Plaza_analytics_Table_NAME"] = PIPELINE_METRICS_TABLE
    os.environ["PLAZA_ANALYTICS_TABLE_NAME"] = PIPELINE_METRICS_TABLE
    os.environ["EXCEPTION_OUTPUT_FILES_TABLE"] = PIPELINE_OUTPUT_FILES_TABLE
    os.environ["Exception_Output_Files_Table"] = PIPELINE_OUTPUT_FILES_TABLE
    os.environ["PIPELINE_BATCH_MODE"] = "1"
    return True


def clear_pipeline_env() -> None:
    import os

    for key in _PIPELINE_TABLE_ENV_KEYS:
        os.environ.pop(key, None)


def register_full_exempt_final_local(
    job: ExceptionJob,
    process_dir,
) -> PlazaMonthlyExceptionInput | None:
    """
    Upload Full Exempt `*_final.xlsx` from the process folder into S3 and
    register plaza_monthly_exception_inputs.slot=full_exempt_final for E15.
    """
    from pathlib import Path

    from app.services.exception_job_s3 import (
        bucket_name,
        build_monthly_input_key,
        object_url,
        s3_client,
    )

    step = find_batch_step_for_job(job.job_uuid)
    if step is None:
        return None
    batch = step.batch
    process_dir = Path(process_dir)
    process_name = str(job.process_name or process_dir.name).strip()
    candidates = [
        process_dir / "output" / f"{process_name}_final.xlsx",
        process_dir / "Intermediate_Files" / "output" / f"{process_name}_final.xlsx",
        process_dir / f"{process_name}_final.xlsx",
    ]
    # Also accept any *_final.xlsx under output/
    out_dir = process_dir / "output"
    if out_dir.is_dir():
        candidates.extend(sorted(out_dir.glob("*_final.xlsx")))
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        logger.warning(
            "Full Exempt final workbook not found under %s", process_dir
        )
        return None

    plaza = batch.plaza
    plaza_name = (plaza.plaza_name if plaza else None) or batch.plaza_identifier
    key = build_monthly_input_key(
        plaza_name=plaza_name,
        year=batch.year,
        month=batch.month,
        slot="full_exempt_final",
        original_file_name=path.name,
    )
    bucket = bucket_name()
    import os

    region = os.getenv("AWS_REGION", "us-east-1").strip() or "us-east-1"
    client = s3_client()
    client.upload_file(
        str(path),
        bucket,
        key,
        ExtraArgs={
            "ContentType": (
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            )
        },
    )
    file_url = object_url(bucket, region, key)
    size = path.stat().st_size

    PlazaMonthlyExceptionInput.query.filter_by(
        plaza_identifier=batch.plaza_identifier,
        year=batch.year,
        month=batch.month,
        slot="full_exempt_final",
        source="pipeline_output",
    ).delete()

    row = PlazaMonthlyExceptionInput(
        plaza_identifier=batch.plaza_identifier,
        year=batch.year,
        month=batch.month,
        slot="full_exempt_final",
        original_file_name=path.name,
        s3_key=key,
        file_url=file_url,
        file_size_bytes=size,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        source="pipeline_output",
    )
    db.session.add(row)
    db.session.commit()
    logger.info(
        "Registered full_exempt_final %s for %s %s-%02d",
        path.name,
        batch.plaza_identifier,
        batch.year,
        batch.month,
    )
    return row


def register_full_exempt_final_from_job(job: ExceptionJob) -> PlazaMonthlyExceptionInput | None:
    """Fallback: reuse an already-registered full_exempt_final row."""
    step = find_batch_step_for_job(job.job_uuid)
    if step is None:
        return None
    batch = step.batch
    return PlazaMonthlyExceptionInput.query.filter_by(
        plaza_identifier=batch.plaza_identifier,
        year=batch.year,
        month=batch.month,
        slot="full_exempt_final",
    ).first()


def on_analytics_job_finished(job: ExceptionJob) -> None:
    """Update batch status when the parallel analytics track finishes (analytics-only batches)."""
    batch = ExceptionPipelineBatch.query.filter_by(
        analytics_job_uuid=job.job_uuid
    ).first()
    if batch is None:
        return
    now = _utc_now()
    if job.status == "cancelled" or str(batch.status or "") == "cancelled":
        if batch.status != "cancelled":
            batch.status = "cancelled"
            batch.progress_message = (
                "Stopped by user. Uploaded input files were kept."
            )
            batch.error_message = "Stopped by user — run progress discarded."
        batch.finished_at = now
        db.session.commit()
        return
    pending = (
        ExceptionPipelineBatchStep.query.filter_by(batch_id=batch.id, status="pending")
        .count()
    )
    active = (
        ExceptionPipelineBatchStep.query.filter(
            ExceptionPipelineBatchStep.batch_id == batch.id,
            ExceptionPipelineBatchStep.status.in_(("queued", "running")),
        ).count()
    )
    # Exception chain still going — leave batch status to the serial stepper.
    if pending or active:
        db.session.commit()
        return
    # No exception steps (or all already terminal): analytics owns the batch finish.
    has_steps = ExceptionPipelineBatchStep.query.filter_by(batch_id=batch.id).count()
    if has_steps and batch.status in {"succeeded", "failed", "cancelled"}:
        return
    if job.status == "succeeded":
        batch.status = "succeeded"
        batch.progress_message = (
            "Plaza analytics finished."
            if not has_steps
            else "All selected programs finished."
        )
        batch.error_message = None
    else:
        # Analytics failure does not fail exception results; only fail when analytics-only.
        if not has_steps:
            batch.status = "failed"
            batch.error_message = job.error_message or "Plaza analytics failed"
            batch.progress_message = "Plaza analytics failed."
        else:
            batch.progress_message = (
                (batch.progress_message or "Exceptions finished")
                + " · Analytics failed"
            )
    batch.finished_at = now
    db.session.commit()


def on_pipeline_child_finished(job: ExceptionJob) -> None:
    """Advance the parent batch after a child exception job completes."""
    step = find_batch_step_for_job(job.job_uuid)
    if step is None:
        return
    batch = step.batch
    now = _utc_now()
    if job.status == "cancelled" or str(batch.status or "") == "cancelled":
        step.status = "cancelled"
        step.error_message = "Stopped by user"
        step.finished_at = now
        if batch.status != "cancelled":
            batch.status = "cancelled"
            batch.progress_message = (
                "Stopped by user. Uploaded input files were kept."
            )
            batch.error_message = "Stopped by user — run progress discarded."
            batch.finished_at = now
        for other in batch.steps:
            if other.status in {"pending", "queued", "running"}:
                other.status = "cancelled"
                other.finished_at = now
                other.error_message = other.error_message or "Stopped by user"
        db.session.commit()
        return

    if job.status == "succeeded":
        step.status = "succeeded"
        step.finished_at = now
        step.error_message = None
        if job.program_code == "full_exempt_e1_e2_e3_e13_e14":
            try:
                register_full_exempt_final_from_job(job)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to register full_exempt_final for pipeline")
        db.session.commit()
        enqueue_next_pipeline_step(batch)
        return

    # failed
    step.status = "failed"
    step.error_message = job.error_message or f"Child job {job.status}"
    step.finished_at = now
    if batch.continue_on_failure:
        db.session.commit()
        enqueue_next_pipeline_step(batch)
    else:
        batch.status = "failed"
        batch.error_message = step.error_message
        batch.finished_at = now
        # Cancel remaining pending steps
        for other in batch.steps:
            if other.status == "pending":
                other.status = "cancelled"
                other.finished_at = now
        db.session.commit()


def _cancel_batch_inplace(
    batch: ExceptionPipelineBatch,
    *,
    reason: str,
    progress_message: str,
    kill_children: bool = False,
) -> list[str]:
    """Mark batch + related jobs cancelled. Returns cancelled job UUIDs."""
    now = _utc_now()
    batch.status = "cancelled"
    batch.progress_message = progress_message
    batch.error_message = reason
    batch.finished_at = now

    job_uuids: list[str] = []
    for step in batch.steps:
        if step.status in {"pending", "queued", "running"}:
            step.status = "cancelled"
            step.finished_at = now
            step.error_message = reason
        if step.child_job_uuid:
            job_uuids.append(str(step.child_job_uuid))
    if batch.analytics_job_uuid:
        job_uuids.append(str(batch.analytics_job_uuid))

    for juuid in job_uuids:
        job = ExceptionJob.query.filter_by(job_uuid=juuid).first()
        if job is None:
            continue
        if job.status in {"queued", "running", "draft"}:
            job.status = "cancelled"
            job.error_message = reason
            job.progress_message = reason
            job.finished_at = now

    if kill_children:
        try:
            from app.services.exception_job_worker import kill_active_job_children

            killed = kill_active_job_children()
            logger.info(
                "Cancelled pipeline batch %s (killed %s active child process(es))",
                batch.batch_uuid,
                killed,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed killing active children for batch %s", batch.batch_uuid
            )
    return job_uuids


def reconcile_duplicate_active_batches() -> int:
    """
    After restart, keep only the newest active batch per plaza+month.
    Older queued/running batches (and their jobs) are cancelled so they do not
    occupy worker slots forever.
    """
    active = (
        ExceptionPipelineBatch.query.filter(
            ExceptionPipelineBatch.status.in_(("queued", "running"))
        )
        .order_by(ExceptionPipelineBatch.id.asc())
        .all()
    )
    if not active:
        return 0

    newest_by_period: dict[tuple[str, int, int], ExceptionPipelineBatch] = {}
    for batch in active:
        key = (batch.plaza_identifier, int(batch.year), int(batch.month))
        newest_by_period[key] = batch  # ascending id → last wins

    cancelled = 0
    reason = (
        "Superseded by a newer File Upload run for this plaza and month "
        "(cleaned up after backend restart)."
    )
    progress = (
        "Stopped — a newer run for this plaza/month is active. "
        "Uploaded input files were kept."
    )
    for batch in active:
        key = (batch.plaza_identifier, int(batch.year), int(batch.month))
        keep = newest_by_period.get(key)
        if keep is None or keep.id == batch.id:
            continue
        _cancel_batch_inplace(
            batch,
            reason=reason,
            progress_message=progress,
            kill_children=False,
        )
        cancelled += 1

    if cancelled:
        db.session.commit()
        try:
            from app.services.exception_job_worker import kill_active_job_children

            kill_active_job_children()
        except Exception:  # noqa: BLE001
            logger.exception("Failed killing children during batch reconcile")
        logger.info(
            "Reconciled duplicate active batches: cancelled %s older run(s)",
            cancelled,
        )
    return cancelled


def supersede_active_batches_for_period(
    *,
    plaza_identifier: str,
    year: int,
    month: int,
    keep_batch_uuid: str,
) -> int:
    """
    Cancel other queued/running batches for the same plaza+month so a new start
    is not blocked by leftover jobs after a restart or a prior incomplete run.
    Monthly uploaded inputs are left unchanged.
    """
    others = (
        ExceptionPipelineBatch.query.filter(
            ExceptionPipelineBatch.plaza_identifier == plaza_identifier,
            ExceptionPipelineBatch.year == int(year),
            ExceptionPipelineBatch.month == int(month),
            ExceptionPipelineBatch.status.in_(("queued", "running")),
            ExceptionPipelineBatch.batch_uuid != keep_batch_uuid,
        )
        .order_by(ExceptionPipelineBatch.id.asc())
        .all()
    )
    if not others:
        return 0

    reason = (
        "Superseded by a new File Upload run for this plaza and month."
    )
    progress = (
        "Stopped — a newer run for this plaza/month took over. "
        "Uploaded input files were kept."
    )
    for other in others:
        _cancel_batch_inplace(
            other,
            reason=reason,
            progress_message=progress,
            kill_children=False,
        )
    db.session.commit()
    # Kill once after marking all superseded jobs cancelled.
    try:
        from app.services.exception_job_worker import kill_active_job_children

        kill_active_job_children()
    except Exception:  # noqa: BLE001
        logger.exception("Failed killing children while superseding batches")
    logger.info(
        "Superseded %s active batch(es) for %s %s-%02d (kept %s)",
        len(others),
        plaza_identifier,
        year,
        month,
        keep_batch_uuid[:8],
    )
    return len(others)


def cancel_batch(batch_uuid: str) -> ExceptionPipelineBatch:
    """
    Stop a running/queued pipeline batch.
    Uploaded monthly input files are left unchanged.
    """
    batch = ExceptionPipelineBatch.query.filter_by(batch_uuid=batch_uuid).first()
    if batch is None:
        raise ValueError("Batch not found")
    if batch.status not in {"queued", "running"}:
        raise ValueError(
            f"Cannot stop batch while status is {batch.status}."
        )

    _cancel_batch_inplace(
        batch,
        reason="Stopped by user — run progress discarded.",
        progress_message="Stopped by user. Uploaded input files were kept.",
        kill_children=True,
    )
    db.session.commit()
    db.session.refresh(batch)
    return batch
