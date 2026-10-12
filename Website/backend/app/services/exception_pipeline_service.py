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
from app.services.pipeline_dependency_catalog import (
    PIPELINE_METRICS_TABLE,
    PIPELINE_OUTPUT_FILES_TABLE,
    evaluate_program_availability,
    get_pipeline_program,
)

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
    return {
        "plaza_identifier": plaza_identifier,
        "year": int(year),
        "month": int(month),
        "present_slots": sorted(present),
        "files": [f.to_dict() for f in files],
        "programs": evaluate_program_availability(present),
    }


def create_batch(
    *,
    plaza_identifier: str,
    year: int,
    month: int,
    program_codes: list[str],
    pipeline_plaza_key: str | None = None,
    continue_on_failure: bool = True,
    created_by_user_id: int | None = None,
) -> ExceptionPipelineBatch:
    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first()
    if plaza is None:
        raise ValueError(f"Unknown plaza_identifier: {plaza_identifier}")

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
                f"pipeline_plaza_key is required for {code}."
            )
        selected.append(program)

    if not selected:
        raise ValueError("Select at least one program.")

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


def enqueue_next_pipeline_step(batch: ExceptionPipelineBatch) -> ExceptionJob | None:
    """Queue the next pending step as a normal ExceptionJob (pipeline env later)."""
    step = (
        ExceptionPipelineBatchStep.query.filter_by(batch_id=batch.id, status="pending")
        .order_by(ExceptionPipelineBatchStep.sort_order.asc())
        .first()
    )
    if step is None:
        batch.status = "succeeded"
        batch.progress_message = "All selected programs finished."
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


def start_batch(batch_uuid: str) -> ExceptionPipelineBatch:
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
    enqueue_next_pipeline_step(batch)
    db.session.refresh(batch)
    return batch


def find_batch_step_for_job(job_uuid: str) -> ExceptionPipelineBatchStep | None:
    return ExceptionPipelineBatchStep.query.filter_by(child_job_uuid=job_uuid).first()


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
    os.environ["EXCEPTION_OUTPUT_FILES_TABLE"] = PIPELINE_OUTPUT_FILES_TABLE
    os.environ["Exception_Output_Files_Table"] = PIPELINE_OUTPUT_FILES_TABLE
    os.environ["PIPELINE_BATCH_MODE"] = "1"
    return True


def clear_pipeline_env() -> None:
    import os

    for key in (
        "Exception_Metrics_Table",
        "EXCEPTION_METRICS_TABLE",
        "EXCEPTION_OUTPUT_FILES_TABLE",
        "Exception_Output_Files_Table",
        "PIPELINE_BATCH_MODE",
    ):
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


def on_pipeline_child_finished(job: ExceptionJob) -> None:
    """Advance the parent batch after a child exception job completes."""
    step = find_batch_step_for_job(job.job_uuid)
    if step is None:
        return
    batch = step.batch
    now = _utc_now()
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

    # failed / cancelled
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
