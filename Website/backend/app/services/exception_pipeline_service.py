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

# Match exception_job_worker max_parallel: keep this many exception steps in flight.
# (Plaza analytics is a separate parallel track and shares the same workers.)
PIPELINE_EXCEPTION_MAX_PARALLEL = 2

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def prune_missing_monthly_inputs(
    plaza_identifier: str, year: int, month: int
) -> int:
    """
    Drop DB rows for monthly inputs whose S3 objects are confirmed gone (404).

    Only deletes on definitive NotFound — never on timeouts/auth blips, so a
    bad HeadObject does not wipe real uploads and leave ghost UI state.
    """
    from app.services.exception_job_s3 import s3_key_confirmed_missing

    rows = (
        PlazaMonthlyExceptionInput.query.filter_by(
            plaza_identifier=plaza_identifier,
            year=int(year),
            month=int(month),
        )
        .order_by(PlazaMonthlyExceptionInput.id.asc())
        .all()
    )
    removed = 0
    for row in rows:
        missing = s3_key_confirmed_missing(row.s3_key)
        if missing is not True:
            continue
        logger.warning(
            "Pruning missing monthly input id=%s plaza=%s %s-%02d slot=%s key=%s",
            row.id,
            plaza_identifier,
            year,
            month,
            row.slot,
            row.s3_key,
        )
        db.session.delete(row)
        removed += 1
    if removed:
        db.session.commit()
    return removed


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
    # Only remove rows when S3 returns a hard 404 (not on transient errors).
    pruned = prune_missing_monthly_inputs(plaza_identifier, year, month)
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
    try:
        from app.services.scrape_vehicle_preview import preview_scrape_vehicles

        scrape_preview = preview_scrape_vehicles(files)
    except Exception:  # noqa: BLE001
        logger.exception("Scrape vehicle preview failed")
        scrape_preview = {}
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
        "pruned_missing_files": int(pruned),
        "scrape_preview": scrape_preview,
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

    prune_missing_monthly_inputs(plaza_identifier, year, month)
    present = present_slots_for_period(plaza_identifier, year, month)
    availability = {
        p["code"]: p for p in evaluate_program_availability(present)
    }

    selected_codes = {str(code).strip() for code in program_codes}
    selected: list[dict] = []
    for code in program_codes:
        program = get_pipeline_program(code)
        if program is None:
            raise ValueError(f"Unknown program_code: {code}")
        info = availability.get(code) or {}
        missing_slots = list(info.get("missing_slots") or [])
        e15_waiting_on_exempt = (
            code == "e15"
            and set(missing_slots) == {"full_exempt_final"}
            and "full_exempt_e1_e2_e3_e13_e14" in selected_codes
        )
        if not info.get("enabled") and not e15_waiting_on_exempt:
            if code == "e15" and set(missing_slots) == {"full_exempt_final"}:
                raise ValueError(
                    "No Full Exempt file is stored for this month. "
                    "Run Exempt Query — Full Process as well."
                )
            missing = ", ".join(missing_slots)
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
        if code == "full_exempt_e1_e2_e3_e13_e14":
            from app.services.plaza_reference_files import (
                full_exempt_reference_block_reason,
                month_bounds,
            )

            period_start, period_end = month_bounds(int(year), int(month))
            block = full_exempt_reference_block_reason(
                plaza_identifier=plaza_identifier,
                pipeline_plaza_key=pipeline_plaza_key,
                start=period_start,
                end=period_end,
                has_rates_upload="rates" in present,
                has_approved_upload="approved_exemption" in present,
            )
            if block:
                raise ValueError(block)
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


def _active_exception_step_count(batch: ExceptionPipelineBatch) -> int:
    return (
        ExceptionPipelineBatchStep.query.filter(
            ExceptionPipelineBatchStep.batch_id == batch.id,
            ExceptionPipelineBatchStep.status.in_(("queued", "running")),
        ).count()
    )


def _producer_codes_for_slot(slot: str) -> list[str]:
    from app.services.pipeline_dependency_catalog import list_pipeline_programs

    key = str(slot or "").strip()
    return [
        p["code"]
        for p in list_pipeline_programs()
        if key in (p.get("produces_slots") or [])
    ]


def _pipeline_step_readiness(
    batch: ExceptionPipelineBatch,
    step: ExceptionPipelineBatchStep,
    present: set[str],
) -> tuple[str, list[str]]:
    """
    Returns (state, missing_slots) where state is:
      ready   — required monthly slots are present; can queue now
      waiting — missing slots may still be produced by an in-batch step
      blocked — missing slots cannot be produced (or producer already failed)
    """
    program = get_pipeline_program(step.program_code)
    if program is None:
        return "blocked", [f"unknown:{step.program_code}"]

    required = list(program.get("required_slots") or [])
    missing = [s for s in required if s not in present]
    if not missing:
        return "ready", []

    steps_by_code = {s.program_code: s for s in (batch.steps or [])}
    for slot in missing:
        producers = _producer_codes_for_slot(slot)
        if not producers:
            return "blocked", missing
        producer_steps = [
            steps_by_code[code] for code in producers if code in steps_by_code
        ]
        if not producer_steps:
            # Needed output is not in this run and not on disk yet.
            return "blocked", missing
        if any(
            str(ps.status or "") in {"pending", "queued", "running"}
            for ps in producer_steps
        ):
            return "waiting", missing
        if not any(str(ps.status or "") == "succeeded" for ps in producer_steps):
            return "blocked", missing
        # Producer succeeded but slot still absent (registration failed).
        return "blocked", missing
    return "blocked", missing


def _fail_pipeline_step(
    batch: ExceptionPipelineBatch,
    step: ExceptionPipelineBatchStep,
    message: str,
) -> bool:
    """
    Mark step failed. Returns False when the whole batch was failed/stopped
    (caller should not enqueue more).
    """
    now = _utc_now()
    step.status = "failed"
    step.error_message = message
    step.finished_at = now
    if batch.continue_on_failure:
        return True
    batch.status = "failed"
    batch.error_message = message
    batch.finished_at = now
    for other in batch.steps:
        if other.status == "pending":
            other.status = "cancelled"
            other.finished_at = now
            other.error_message = other.error_message or "Stopped after earlier failure"
    return False


def _queue_pipeline_step_job(
    batch: ExceptionPipelineBatch,
    step: ExceptionPipelineBatchStep,
    program: dict,
) -> ExceptionJob:
    pipeline_key = batch.pipeline_plaza_key or (
        batch.plaza.plaza_name if batch.plaza else None
    ) or "PLAZA"
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
    return job


def enqueue_ready_pipeline_steps(
    batch: ExceptionPipelineBatch,
    *,
    max_parallel: int = PIPELINE_EXCEPTION_MAX_PARALLEL,
) -> list[ExceptionJob]:
    """
    Queue up to max_parallel ready exception steps for this batch.

    Independent programs (E04/E05/…) can run together. Dependents such as E15
    stay pending until required produced slots (e.g. full_exempt_final) exist.
    """
    if str(batch.status or "") == "cancelled":
        return []

    limit = max(1, int(max_parallel or PIPELINE_EXCEPTION_MAX_PARALLEL))
    queued: list[ExceptionJob] = []

    while True:
        active = _active_exception_step_count(batch)
        if active >= limit:
            break

        pending = (
            ExceptionPipelineBatchStep.query.filter_by(
                batch_id=batch.id, status="pending"
            )
            .order_by(ExceptionPipelineBatchStep.sort_order.asc())
            .all()
        )
        if not pending:
            if active == 0 and str(batch.status or "") != "cancelled":
                batch.status = "succeeded"
                batch.progress_message = "All selected exception programs finished."
                batch.finished_at = _utc_now()
                db.session.commit()
            break

        present = present_slots_for_period(
            batch.plaza_identifier, batch.year, batch.month
        )
        chosen: ExceptionPipelineBatchStep | None = None
        chosen_program: dict | None = None
        saw_waiting = False

        for step in pending:
            program = get_pipeline_program(step.program_code)
            if program is None:
                keep_going = _fail_pipeline_step(
                    batch,
                    step,
                    f"Unknown program {step.program_code}",
                )
                db.session.commit()
                if not keep_going:
                    return queued
                continue

            state, missing = _pipeline_step_readiness(batch, step, present)
            if state == "ready":
                chosen = step
                chosen_program = program
                break
            if state == "waiting":
                saw_waiting = True
                continue
            keep_going = _fail_pipeline_step(
                batch,
                step,
                f"Missing required slots: {', '.join(missing) or 'unknown'}",
            )
            db.session.commit()
            if not keep_going:
                return queued

        if chosen is None or chosen_program is None:
            # Nothing ready: either waiting on in-flight/pending producers, or
            # only blocked steps (already failed above).
            if (
                active == 0
                and not saw_waiting
                and str(batch.status or "") not in {"failed", "cancelled"}
            ):
                # No pending left that can ever run.
                still_pending = (
                    ExceptionPipelineBatchStep.query.filter_by(
                        batch_id=batch.id, status="pending"
                    ).count()
                )
                if still_pending == 0:
                    batch.status = "succeeded"
                    batch.progress_message = (
                        "All selected exception programs finished."
                    )
                    batch.finished_at = _utc_now()
                    db.session.commit()
            break

        job = _queue_pipeline_step_job(batch, chosen, chosen_program)
        queued.append(job)
        batch.status = "running"
        if batch.started_at is None:
            batch.started_at = _utc_now()

        active_labels = []
        for s in batch.steps:
            if s.status in {"queued", "running"}:
                prog = get_pipeline_program(s.program_code)
                active_labels.append(
                    (prog or {}).get("label") or s.program_code
                )
        batch.progress_message = (
            f"Running {len(active_labels)} in parallel: "
            + ", ".join(active_labels)
            if len(active_labels) > 1
            else f"Queued {active_labels[0] if active_labels else chosen.program_code}"
        )
        db.session.commit()

    return queued


def enqueue_next_pipeline_step(batch: ExceptionPipelineBatch) -> ExceptionJob | None:
    """Queue ready exception steps (up to worker parallelism). Returns last queued job."""
    jobs = enqueue_ready_pipeline_steps(batch)
    return jobs[-1] if jobs else None


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
_PIPELINE_TABLE_ENV_KEYS = (
    "Exception_Metrics_Table",
    "EXCEPTION_METRICS_TABLE",
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
    os.environ["EXCEPTION_OUTPUT_FILES_TABLE"] = PIPELINE_OUTPUT_FILES_TABLE
    os.environ["Exception_Output_Files_Table"] = PIPELINE_OUTPUT_FILES_TABLE
    os.environ["PIPELINE_BATCH_MODE"] = "1"
    return True


def clear_pipeline_env() -> None:
    import os

    for key in _PIPELINE_TABLE_ENV_KEYS:
        os.environ.pop(key, None)


def find_full_exempt_final_path(process_dir, process_name: str | None = None):
    """Locate Full Exempt `*_final.xlsx` under the process folder."""
    from pathlib import Path

    process_dir = Path(process_dir)
    name = str(process_name or process_dir.name).strip()
    candidates = [
        process_dir / "output" / f"{name}_final.xlsx",
        process_dir / "Intermediate_Files" / "output" / f"{name}_final.xlsx",
        process_dir / f"{name}_final.xlsx",
    ]
    out_dir = process_dir / "output"
    if out_dir.is_dir():
        candidates.extend(sorted(out_dir.glob("*_final.xlsx")))
    return next((p for p in candidates if p.is_file()), None)


def build_full_exempt_final_display_name(
    *,
    plaza_name: str,
    year: int,
    month: int,
    created_at=None,
    suffix: str = ".xlsx",
) -> str:
    """
    Human-readable Full Exempt final name for E15 picker / job attachments.

    Example: Bassi_Exempt_Final_Sep2026_20261014_173045.xlsx
    """
    import calendar
    import re
    from datetime import datetime, timezone

    plaza = re.sub(r"[^\w.\- ]+", "", str(plaza_name or "Plaza")).strip(" ._") or "Plaza"
    plaza = re.sub(r"\s+", "_", plaza)
    try:
        month_i = int(month)
        year_i = int(year)
        month_abbr = calendar.month_abbr[month_i] if 1 <= month_i <= 12 else f"M{month_i}"
        period = f"{month_abbr}{year_i}"
    except (TypeError, ValueError):
        period = "Unknown"

    stamp = created_at
    if stamp is None:
        stamp = datetime.now(timezone.utc)
    elif getattr(stamp, "tzinfo", None) is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    else:
        stamp = stamp.astimezone(timezone.utc)
    ts = stamp.strftime("%Y%m%d_%H%M%S")

    ext = suffix if str(suffix).startswith(".") else f".{suffix}"
    if not ext:
        ext = ".xlsx"
    return f"{plaza}_Exempt_Final_{period}_{ts}{ext}"


def _periods_from_final_workbook(path) -> list[tuple[int, int]]:
    """Unique (year, month) from Date & Time on the exempt final workbook."""
    try:
        import pandas as pd
    except ImportError:
        return []
    try:
        frame = pd.read_excel(path, sheet_name=0, dtype=str)
    except Exception:  # noqa: BLE001
        logger.exception("Could not read final workbook for period detection: %s", path)
        return []
    if frame is None or frame.empty:
        return []
    date_col = None
    for col in frame.columns:
        key = str(col).strip().casefold().replace("_", " ")
        if key in {"date & time", "date and time", "datetime", "date"}:
            date_col = col
            break
    if date_col is None:
        return []
    parsed = pd.to_datetime(frame[date_col], errors="coerce", dayfirst=True)
    if parsed.isna().all():
        parsed = pd.to_datetime(frame[date_col], errors="coerce", dayfirst=False)
    periods: set[tuple[int, int]] = set()
    for stamp in parsed.dropna():
        year = int(stamp.year)
        month = int(stamp.month)
        if 1990 <= year <= 2100 and 1 <= month <= 12:
            periods.add((year, month))
    return sorted(periods)


def _resolve_full_exempt_periods(job: ExceptionJob, path) -> list[tuple[int, int]]:
    """
    Periods for monthly S3 registration (feeds E15).

    Prefer pipeline batch year/month; else dates in the workbook;
    else the job created_at month.
    """
    step = find_batch_step_for_job(job.job_uuid)
    if step is not None and step.batch is not None:
        return [(int(step.batch.year), int(step.batch.month))]

    from_file = _periods_from_final_workbook(path)
    if from_file:
        return from_file

    created = job.created_at or _utc_now()
    return [(int(created.year), int(created.month))]


def register_full_exempt_final_local(
    job: ExceptionJob,
    process_dir,
) -> PlazaMonthlyExceptionInput | None:
    """
    Upload Full Exempt `*_final.xlsx` to S3 and register
    plaza_monthly_exception_inputs.slot=full_exempt_final for E15.

    Works for one-click pipeline batches and separate Exempt Query jobs.
    """
    import os
    from pathlib import Path

    from app.services.exception_job_s3 import (
        bucket_name,
        build_monthly_input_key,
        object_url,
        s3_client,
    )

    process_dir = Path(process_dir)
    process_name = str(job.process_name or process_dir.name).strip()
    path = find_full_exempt_final_path(process_dir, process_name)
    if path is None:
        logger.warning(
            "Full Exempt final workbook not found under %s", process_dir
        )
        return None

    plaza_identifier = str(job.plaza_identifier or "").strip()
    if not plaza_identifier:
        logger.warning("Job %s has no plaza_identifier — skip final upload", job.job_uuid)
        return None

    plaza = job.plaza or Plaza.query.filter_by(plaza_identifier=plaza_identifier).first()
    plaza_name = (plaza.plaza_name if plaza else None) or plaza_identifier

    periods = _resolve_full_exempt_periods(job, path)
    if not periods:
        logger.warning("No periods resolved for full_exempt_final on job %s", job.job_uuid)
        return None

    # One S3 object (keyed by primary period); same key registered for every month.
    primary_year, primary_month = periods[0]
    friendly_name = build_full_exempt_final_display_name(
        plaza_name=plaza_name,
        year=primary_year,
        month=primary_month,
        created_at=_utc_now(),
        suffix=path.suffix or ".xlsx",
    )
    from flask import current_app

    from app.services.exception_job_s3 import LOCAL_OBJECT_PREFIX
    from app.services.repo_paths import backend_root

    publish = bool(current_app.config.get("PUBLISH_EXCEPTION_RESULTS", True))
    if publish:
        key = build_monthly_input_key(
            plaza_name=plaza_name,
            year=primary_year,
            month=primary_month,
            slot="full_exempt_final",
            original_file_name=friendly_name,
        )
        bucket = bucket_name()
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
    else:
        import shutil

        dest_dir = (
            backend_root()
            / "var"
            / "exception-outputs"
            / plaza_identifier
            / f"{primary_year}-{primary_month:02d}"
        )
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / friendly_name
        shutil.copy2(path, dest)
        key = f"{LOCAL_OBJECT_PREFIX}{dest}"
        file_url = None
        logger.info(
            "Kept full_exempt_final on disk (S3 upload off): %s", dest
        )
    size = path.stat().st_size
    content_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    first_row: PlazaMonthlyExceptionInput | None = None
    for year, month in periods:
        PlazaMonthlyExceptionInput.query.filter_by(
            plaza_identifier=plaza_identifier,
            year=year,
            month=month,
            slot="full_exempt_final",
            source="pipeline_output",
        ).delete()
        row = PlazaMonthlyExceptionInput(
            plaza_identifier=plaza_identifier,
            year=year,
            month=month,
            slot="full_exempt_final",
            original_file_name=friendly_name,
            s3_key=key,
            file_url=file_url,
            file_size_bytes=size,
            content_type=content_type,
            source="pipeline_output",
        )
        db.session.add(row)
        if first_row is None:
            first_row = row

    db.session.commit()
    period_label = ", ".join(f"{y}-{m:02d}" for y, m in periods)
    logger.info(
        "Registered full_exempt_final %s for %s periods=[%s]",
        friendly_name,
        plaza_identifier,
        period_label,
    )
    return first_row


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
        if step.status in {"pending", "queued", "running", "interrupted"}:
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
        if job.status in {"queued", "running", "draft", "interrupted"}:
            job.status = "cancelled"
            job.error_message = reason
            job.progress_message = reason
            job.finished_at = now

    if kill_children:
        try:
            from app.services.exception_job_worker import stop_job_runtime_resources

            cleanup = stop_job_runtime_resources()
            killed = int(cleanup.get("killed_children") or 0)
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
            from app.services.exception_job_worker import stop_job_runtime_resources

            stop_job_runtime_resources()
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
        from app.services.exception_job_worker import stop_job_runtime_resources

        stop_job_runtime_resources()
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


def resume_interrupted_batch(batch_uuid: str) -> ExceptionPipelineBatch:
    """Queue interrupted work again. Pending steps stay pending and can start."""
    from app.services.exception_job_worker import requeue_interrupted_job

    batch = ExceptionPipelineBatch.query.filter_by(batch_uuid=batch_uuid).first()
    if batch is None:
        raise ValueError("Batch not found")
    if batch.status != "interrupted":
        raise ValueError(
            f"Cannot resume batch while status is {batch.status}."
        )

    for step in batch.steps:
        if step.status != "interrupted":
            continue
        child = None
        if step.child_job_uuid:
            child = ExceptionJob.query.filter_by(job_uuid=step.child_job_uuid).first()
        if child is not None and child.status == "interrupted":
            requeue_interrupted_job(child)
            step.status = "queued"
        else:
            step.status = "pending"
            step.child_job_uuid = None
        step.error_message = None
        step.finished_at = None

    if batch.analytics_job_uuid:
        analytics = ExceptionJob.query.filter_by(
            job_uuid=batch.analytics_job_uuid
        ).first()
        if analytics is not None and analytics.status == "interrupted":
            requeue_interrupted_job(analytics)

    batch.status = "running"
    batch.error_message = None
    batch.finished_at = None
    batch.progress_message = "Resumed. Interrupted work is queued again."
    db.session.commit()
    enqueue_ready_pipeline_steps(batch)
    db.session.refresh(batch)
    return batch


def cancel_batch(batch_uuid: str) -> ExceptionPipelineBatch:
    """
    Stop a running/queued pipeline batch.
    Uploaded monthly input files are left unchanged.
    """
    batch = ExceptionPipelineBatch.query.filter_by(batch_uuid=batch_uuid).first()
    if batch is None:
        raise ValueError("Batch not found")
    if batch.status not in {"queued", "running", "interrupted"}:
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
