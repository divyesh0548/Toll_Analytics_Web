"""Exception processing job APIs (programs catalog + upload + start)."""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.audit_exception import AuditExceptionOutputFile
from app.models.exception_job import ExceptionJob, ExceptionJobFile
from app.models.exception_pipeline import PlazaMonthlyExceptionInput
from app.models.plaza import Plaza
from app.services.auth_tokens import deny_viewer_writes, get_current_user
from app.services.db_session import commit_with_retry
from app.services.exception_job_s3 import (
    bucket_name,
    delete_object,
    head_object_size,
    job_input_key_prefix,
    object_url,
    presign_put_upload,
)
from app.services.exception_program_catalog import (
    get_program,
    job_list_codes_for_program,
    list_programs,
    load_annexure_server_defaults,
    load_pipeline_plaza_keys,
)
from app.services.plaza_entity_map import resolve_entity_name
from app.utils.api_log import log_fail, log_ok
from config import Config

exception_jobs_bp = Blueprint("exception_jobs", __name__)

EDITABLE_STATUSES = {"draft", "failed"}


@exception_jobs_bp.before_request
def _require_auth():
    if not get_current_user():
        log_fail("exception_jobs: auth required")
        return {"error": "Authentication required"}, 401
    denied = deny_viewer_writes()
    if denied:
        log_fail("exception_jobs: viewer write blocked")
        return denied


@exception_jobs_bp.get("/programs")
def programs_catalog():
    log_ok("exception programs catalog")
    return jsonify(
        {
            "programs": list_programs(),
            "pipeline_plaza_keys": load_pipeline_plaza_keys(),
        }
    )


@exception_jobs_bp.get("/annexure-defaults")
def annexure_defaults():
    """Rates and approved-exemption files stored for this plaza that cover today."""
    plaza_key = (request.args.get("pipeline_plaza_key") or "").strip().upper()
    plaza_identifier = (request.args.get("plaza_identifier") or "").strip()
    if not plaza_key and not plaza_identifier:
        return jsonify({"error": "pipeline_plaza_key or plaza_identifier is required"}), 400
    year = request.args.get("year")
    month = request.args.get("month")
    try:
        year_i = int(year) if year else None
        month_i = int(month) if month else None
    except (TypeError, ValueError):
        return jsonify({"error": "year and month must be integers"}), 400
    defaults = load_annexure_server_defaults(
        plaza_key, plaza_identifier, year_i, month_i
    )
    log_ok(f"annexure defaults for {plaza_key or plaza_identifier}")
    return jsonify(defaults)


@exception_jobs_bp.get("/staging-invalid-files")
def list_staging_invalid_files():
    """
    Non-final E05 invalid_table files for a plaza (latest first).
    Used by the E05 job UI dropdown.
    """
    plaza_identifier = (request.args.get("plaza_identifier") or "").strip()
    if not plaza_identifier:
        return jsonify({"error": "plaza_identifier is required"}), 400
    exception_type_id = int(request.args.get("exception_type_id") or 5)
    rows = (
        AuditExceptionOutputFile.query.filter_by(
            plaza_identifier=plaza_identifier,
            exception_type_id=exception_type_id,
            is_final_output=False,
        )
        .order_by(AuditExceptionOutputFile.created_at.desc())
        .limit(100)
        .all()
    )
    log_ok(
        f"staging invalid files plaza={plaza_identifier} count={len(rows)}"
    )
    return jsonify({"files": [r.to_dict() for r in rows]})


@exception_jobs_bp.get("/exempt-final-files")
def list_exempt_final_files():
    """
    Full Exempt *_final.xlsx files registered for a plaza (latest first).

    Source: plaza_monthly_exception_inputs.slot=full_exempt_final
    (written when Exempt Query — Full Process succeeds).
    Used by the E15 From-plaza picker on separate jobs.
    """
    import calendar

    plaza_identifier = (request.args.get("plaza_identifier") or "").strip()
    if not plaza_identifier:
        return jsonify({"error": "plaza_identifier is required"}), 400
    try:
        limit = max(1, min(int(request.args.get("limit") or 20), 50))
    except (TypeError, ValueError):
        limit = 20

    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first()
    plaza_name = (plaza.plaza_name if plaza else None) or plaza_identifier

    rows = (
        PlazaMonthlyExceptionInput.query.filter_by(
            plaza_identifier=plaza_identifier,
            slot="full_exempt_final",
        )
        .order_by(PlazaMonthlyExceptionInput.created_at.desc())
        .limit(limit * 3)
        .all()
    )
    # Same S3 object may be registered for multiple months — keep newest per key.
    from app.services.exception_pipeline_service import (
        build_full_exempt_final_display_name,
    )

    seen_keys: set[str] = set()
    files: list[dict] = []
    for row in rows:
        key = str(row.s3_key or "").strip()
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        payload = row.to_dict()
        month_abbr = (
            calendar.month_abbr[int(row.month)]
            if 1 <= int(row.month) <= 12
            else str(row.month)
        )
        payload["period_label"] = f"{month_abbr} {int(row.year)}"
        payload["plaza_name"] = plaza_name
        # Prefer a plaza + period + timestamp name (also rewrites legacy cryptic names).
        stored = str(row.original_file_name or "").strip()
        already_friendly = (
            "_Exempt_Final_" in stored and plaza_name.replace(" ", "_") in stored.replace(" ", "_")
        )
        if already_friendly:
            display_name = stored
        else:
            display_name = build_full_exempt_final_display_name(
                plaza_name=plaza_name,
                year=int(row.year),
                month=int(row.month),
                created_at=row.created_at,
                suffix=".xlsx",
            )
        payload["display_name"] = display_name
        files.append(payload)
        if len(files) >= limit:
            break

    log_ok(
        f"exempt final files plaza={plaza_identifier} count={len(files)}"
    )
    return jsonify({"files": files})


@exception_jobs_bp.get("")
def list_jobs():
    plaza_identifier = (request.args.get("plaza_identifier") or "").strip()
    program_code = (request.args.get("program_code") or "").strip()
    query = ExceptionJob.query.order_by(ExceptionJob.id.desc())
    if plaza_identifier:
        query = query.filter_by(plaza_identifier=plaza_identifier)
    if program_code:
        # Support group cards (e05_group → valid_invalid_lookup + e05) and
        # comma-separated codes from the UI.
        raw_codes = [c.strip() for c in program_code.split(",") if c.strip()]
        codes: list[str] = []
        for raw in raw_codes:
            expanded = job_list_codes_for_program(raw)
            codes.extend(expanded or [raw])
        codes = list(dict.fromkeys(codes))
        if len(codes) == 1:
            query = query.filter_by(program_code=codes[0])
        elif codes:
            query = query.filter(ExceptionJob.program_code.in_(codes))
    # Jobs are filtered by program when provided — no program prefix in the name.
    # Mixed lists (no program_code) include the query short name.
    # For a process group, still show which step (prep vs main) on the job row.
    include_program = not bool(program_code)
    if program_code:
        codes_for_ui = job_list_codes_for_program(program_code.split(",")[0].strip())
        include_program = len(codes_for_ui) > 1
    jobs = query.limit(100).all()
    return jsonify(
        {
            "jobs": [
                j.to_dict(
                    include_files=False,
                    include_program_in_name=include_program,
                )
                for j in jobs
            ]
        }
    )


@exception_jobs_bp.post("")
def create_job():
    data = request.get_json(silent=True) or {}
    program_code = str(data.get("program_code") or "").strip()
    plaza_identifier = str(data.get("plaza_identifier") or "").strip()
    pipeline_plaza_key = str(data.get("pipeline_plaza_key") or "").strip().upper()

    program = get_program(program_code)
    if program is None:
        return jsonify({"error": f"Unknown program_code: {program_code}"}), 400
    if program.get("is_process_group"):
        return (
            jsonify(
                {
                    "error": (
                        "Pick a process under this program "
                        "(Valid/Invalid Lookup or main Invalid Lookup)."
                    ),
                }
            ),
            400,
        )
    if not program.get("enabled"):
        return jsonify({"error": f"Program {program_code} is not enabled yet."}), 400

    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first()
    if plaza is None:
        return jsonify({"error": "Plaza not found"}), 404

    needs_pipeline_key = bool(program.get("requires_pipeline_plaza_key"))
    if needs_pipeline_key:
        keys = load_pipeline_plaza_keys()
        if pipeline_plaza_key not in keys:
            return (
                jsonify(
                    {
                        "error": (
                            f"pipeline_plaza_key {pipeline_plaza_key!r} is not in "
                            "codes_dump.json for the Full Exempt pipeline."
                        ),
                        "pipeline_plaza_keys": keys,
                    }
                ),
                400,
            )
    else:
        # E4-style programs: Website plaza only; entity_name from shared map.
        pipeline_plaza_key = pipeline_plaza_key or str(plaza.plaza_name or "").strip().upper()
        if program.get("uses_entity_map") and not resolve_entity_name(plaza_identifier):
            return (
                jsonify(
                    {
                        "error": (
                            f"No entity_name mapped for plaza {plaza.plaza_name!r} "
                            f"({plaza_identifier}). Add it in "
                            "Exeption Programs/common/plaza_entity_map.json."
                        ),
                    }
                ),
                400,
            )

    user = get_current_user()
    job = ExceptionJob(
        program_code=program_code,
        plaza_identifier=plaza_identifier,
        pipeline_plaza_key=pipeline_plaza_key,
        status="draft",
        progress_message="Draft — upload input files, then Start.",
        created_by_user_id=user.id if user else None,
        process_name=None,
    )
    db.session.add(job)
    db.session.commit()
    # Assign process_name after id exists
    job.process_name = f"web_{job.job_uuid.replace('-', '')[:16]}"
    db.session.commit()
    log_ok(f"created exception job {job.job_uuid}")
    return jsonify({"job": job.to_dict()}), 201


@exception_jobs_bp.get("/<job_uuid>")
def get_job(job_uuid: str):
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"job": job.to_dict()})


@exception_jobs_bp.delete("/<job_uuid>")
def delete_job(job_uuid: str):
    """
    Delete a job and its input files.

    Keeps audit/pipeline outputs and shared scrape caches. Stops the job first
    if it is still queued/running.
    """
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404

    cleanup = {"killed_children": 0, "removed_chrome_nodes": 0}
    if job.status in {"queued", "running"}:
        from datetime import datetime, timezone

        from app.services.exception_job_worker import stop_job_runtime_resources

        job.status = "failed"
        job.error_message = "Stopped — job deleted."
        job.progress_message = "Stopped for delete."
        job.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        try:
            cleanup = stop_job_runtime_resources()
        except Exception as exc:  # noqa: BLE001
            log_fail(f"delete-job stop error for {job.job_uuid}: {exc}")

    from app.services.exception_job_cleanup import delete_exception_job

    result = delete_exception_job(job)
    log_ok(
        f"deleted exception job {result.get('job_uuid')} "
        f"(s3={result.get('deleted_s3_keys')}, "
        f"local={result.get('local_workspace_purged')}, "
        f"killed={cleanup.get('killed_children', 0)})"
    )
    return jsonify({"ok": True, "deleted": result, "cleanup": cleanup})


def _editable_job_or_error(job_uuid: str):
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return None, (jsonify({"error": "Job not found"}), 404)
    if job.status not in EDITABLE_STATUSES:
        return None, (
            jsonify({"error": f"Cannot upload while job status is {job.status}."}),
            409,
        )
    return job, None


def _slot_cfg_or_error(job: ExceptionJob, slot: str):
    program = get_program(job.program_code)
    if program is None:
        return None, (jsonify({"error": "Program missing from catalog"}), 500)
    slot_cfg = next((s for s in program["input_slots"] if s["key"] == slot), None)
    if slot_cfg is None:
        return None, (jsonify({"error": f"Invalid slot: {slot}"}), 400)
    return slot_cfg, None


@exception_jobs_bp.post("/<job_uuid>/files/presign")
def presign_job_file(job_uuid: str):
    """Return a short-lived S3 PUT URL; browser uploads directly to S3."""
    job, err = _editable_job_or_error(job_uuid)
    if err:
        return err

    body = request.get_json(silent=True) or {}
    slot = str(body.get("slot") or "").strip()
    slot_cfg, err = _slot_cfg_or_error(job, slot)
    if err:
        return err

    original_name = secure_filename(str(body.get("file_name") or "")) or "upload.bin"
    content_type = str(body.get("content_type") or "").strip() or "application/octet-stream"
    try:
        file_size = int(body.get("file_size_bytes") or 0)
    except (TypeError, ValueError):
        file_size = 0
    if file_size <= 0:
        return jsonify({"error": "file_size_bytes must be > 0"}), 400
    max_bytes = int(getattr(Config, "MAX_CONTENT_LENGTH", 0) or 0)
    if max_bytes and file_size > max_bytes:
        return (
            jsonify({"error": f"File too large (max {max_bytes} bytes)."}),
            413,
        )

    # Single-file slots: replace previous object(s) before issuing a new key.
    if not slot_cfg.get("multiple"):
        existing = ExceptionJobFile.query.filter_by(job_id=job.id, slot=slot).all()
        for row in existing:
            try:
                delete_object(row.s3_key)
            except Exception:  # noqa: BLE001
                pass
            db.session.delete(row)
        commit_with_retry()

    plaza = job.plaza
    plaza_name = plaza.plaza_name if plaza else job.pipeline_plaza_key
    try:
        signed = presign_put_upload(
            plaza_name=plaza_name,
            job_uuid=job.job_uuid,
            slot=slot,
            original_file_name=original_name,
            content_type=content_type,
        )
    except Exception as exc:  # noqa: BLE001
        log_fail(f"exception job presign failed: {exc}")
        return jsonify({"error": str(exc)}), 500

    log_ok(f"presign {original_name} for job {job.job_uuid} slot={slot}")
    return jsonify(
        {
            "upload_url": signed["upload_url"],
            "s3_key": signed["s3_key"],
            "file_url": signed["file_url"],
            "content_type": signed["content_type"],
            "expires_in": signed["expires_in"],
            "slot": slot,
            "original_file_name": original_name,
            "file_size_bytes": file_size,
        }
    ), 200


@exception_jobs_bp.post("/<job_uuid>/files/complete")
def complete_job_file(job_uuid: str):
    """Register an ExceptionJobFile after a successful browser PUT to S3."""
    job, err = _editable_job_or_error(job_uuid)
    if err:
        return err

    body = request.get_json(silent=True) or {}
    slot = str(body.get("slot") or "").strip()
    slot_cfg, err = _slot_cfg_or_error(job, slot)
    if err:
        return err

    s3_key = str(body.get("s3_key") or "").strip()
    original_name = (
        secure_filename(str(body.get("original_file_name") or body.get("file_name") or ""))
        or "upload.bin"
    )
    try:
        declared_size = int(body.get("file_size_bytes") or 0)
    except (TypeError, ValueError):
        declared_size = 0

    if not s3_key:
        return jsonify({"error": "s3_key is required"}), 400

    plaza = job.plaza
    plaza_name = plaza.plaza_name if plaza else job.pipeline_plaza_key
    allowed_prefix = job_input_key_prefix(plaza_name=plaza_name, job_uuid=job.job_uuid)
    if not s3_key.startswith(allowed_prefix):
        return jsonify({"error": "s3_key does not belong to this job"}), 400

    size = head_object_size(s3_key)
    if size is None:
        return jsonify({"error": "S3 object not found — upload may have failed."}), 400
    if size <= 0:
        try:
            delete_object(s3_key)
        except Exception:  # noqa: BLE001
            pass
        return jsonify({"error": "Uploaded file is empty"}), 400
    if declared_size > 0 and abs(size - declared_size) > 0:
        # Prefer actual S3 size; warn in logs only (browser size is advisory).
        log_ok(
            f"complete size mismatch job={job.job_uuid} declared={declared_size} "
            f"s3={size} key={s3_key}"
        )

    # Single-file slots: ensure only one DB row (presign already deleted S3).
    if not slot_cfg.get("multiple"):
        existing = ExceptionJobFile.query.filter_by(job_id=job.id, slot=slot).all()
        for row in existing:
            if row.s3_key and row.s3_key != s3_key:
                try:
                    delete_object(row.s3_key)
                except Exception:  # noqa: BLE001
                    pass
            db.session.delete(row)

    region = os.getenv("AWS_REGION", "us-east-1")
    file_url = str(body.get("file_url") or "").strip() or object_url(
        bucket_name(), region, s3_key
    )

    row = ExceptionJobFile(
        job_id=job.id,
        slot=slot,
        original_file_name=original_name,
        s3_key=s3_key,
        file_url=file_url,
        file_size_bytes=size,
    )
    db.session.add(row)
    if job.status == "failed":
        job.status = "draft"
        job.error_message = None
        job.progress_message = "Draft — files updated after failure."
    commit_with_retry()

    log_ok(f"completed upload {original_name} to job {job.job_uuid} slot={slot}")
    return jsonify({"file": row.to_dict(), "job": job.to_dict()}), 201


@exception_jobs_bp.delete("/<job_uuid>/files/<int:file_id>")
def delete_job_file(job_uuid: str, file_id: int):
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    if job.status not in EDITABLE_STATUSES:
        return (
            jsonify({"error": f"Cannot delete files while job status is {job.status}."}),
            409,
        )
    row = ExceptionJobFile.query.filter_by(id=file_id, job_id=job.id).first()
    if row is None:
        return jsonify({"error": "File not found"}), 404

    s3_key = str(row.s3_key or "").strip()
    staging_rows = []
    monthly_exempt_rows = []
    if s3_key:
        staging_rows = (
            AuditExceptionOutputFile.query.filter_by(
                s3_key=s3_key,
                is_final_output=False,
            ).all()
        )
        monthly_exempt_rows = (
            PlazaMonthlyExceptionInput.query.filter_by(
                s3_key=s3_key,
                slot="full_exempt_final",
            ).all()
        )

    # Failed jobs: hard-delete S3 + any staging output-file DB row.
    # Draft + staging / exempt-final attach: only detach from the job (keep S3).
    # Draft + normal upload: delete the uploaded S3 object.
    shared_reuse = bool(staging_rows or monthly_exempt_rows)
    hard_delete_s3 = job.status == "failed" or not shared_reuse
    # Never delete monthly Full Exempt finals — they feed E15 reuse.
    if monthly_exempt_rows:
        hard_delete_s3 = False
    if s3_key and hard_delete_s3:
        try:
            delete_object(s3_key)
        except Exception as exc:  # noqa: BLE001
            log_fail(f"S3 delete failed (continuing DB delete): {exc}")

    if job.status == "failed" and staging_rows:
        for staging in staging_rows:
            db.session.delete(staging)

    db.session.delete(row)
    db.session.commit()
    log_ok(
        f"deleted file {file_id} from job {job.job_uuid} "
        f"(status={job.status}, hard_s3={hard_delete_s3}, "
        f"staging_rows={len(staging_rows)}, "
        f"monthly_exempt={len(monthly_exempt_rows)})"
    )
    return jsonify({"ok": True, "job": job.to_dict()})


@exception_jobs_bp.post("/<job_uuid>/attach-staging")
def attach_staging_invalid(job_uuid: str):
    """Attach an existing staging invalid_table S3 object as the job's invalid_table slot."""
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    if job.status not in EDITABLE_STATUSES:
        return (
            jsonify({"error": f"Cannot attach while job status is {job.status}."}),
            409,
        )
    program = get_program(job.program_code)
    if program is None or not program.get("allows_staging_invalid_pick"):
        return jsonify({"error": "This program does not support staging picks."}), 400

    data = request.get_json(silent=True) or {}
    try:
        output_file_id = int(data.get("output_file_id") or 0)
    except (TypeError, ValueError):
        output_file_id = 0
    if not output_file_id:
        return jsonify({"error": "output_file_id is required"}), 400

    staging = AuditExceptionOutputFile.query.filter_by(
        id=output_file_id,
        plaza_identifier=job.plaza_identifier,
        is_final_output=False,
    ).first()
    if staging is None:
        return jsonify({"error": "Staging file not found for this plaza."}), 404

    existing = ExceptionJobFile.query.filter_by(
        job_id=job.id, slot="invalid_table"
    ).all()
    for row in existing:
        # Only delete re-uploaded inputs, never staging S3 objects.
        staging_keys = {
            r.s3_key
            for r in AuditExceptionOutputFile.query.filter_by(
                is_final_output=False
            ).all()
            if r.s3_key
        }
        if row.s3_key and row.s3_key not in staging_keys:
            try:
                delete_object(row.s3_key)
            except Exception:  # noqa: BLE001
                pass
        db.session.delete(row)

    attached = ExceptionJobFile(
        job_id=job.id,
        slot="invalid_table",
        original_file_name=staging.file_name or staging.original_file_name or "invalid_table.csv",
        s3_key=staging.s3_key,
        file_url=staging.file_url,
        file_size_bytes=staging.file_size_bytes,
    )
    db.session.add(attached)
    if job.status == "failed":
        job.status = "draft"
        job.error_message = None
        job.progress_message = "Draft — staging invalid table attached."
    else:
        job.progress_message = "Draft — staging invalid table attached."
    db.session.commit()
    log_ok(
        f"attached staging output_file_id={staging.id} to job {job.job_uuid}"
    )
    return jsonify({"file": attached.to_dict(), "job": job.to_dict()}), 201


@exception_jobs_bp.post("/<job_uuid>/attach-exempt-final")
def attach_exempt_final(job_uuid: str):
    """
    Attach a registered Full Exempt final (monthly input) as the E15 from_plaza slot.
    Does not delete the monthly S3 object — only links it onto the job.
    """
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    if job.status not in EDITABLE_STATUSES:
        return (
            jsonify({"error": f"Cannot attach while job status is {job.status}."}),
            409,
        )
    program = get_program(job.program_code)
    if program is None or not program.get("allows_exempt_final_pick"):
        return jsonify({"error": "This program does not support exempt-final picks."}), 400

    data = request.get_json(silent=True) or {}
    try:
        monthly_input_id = int(data.get("monthly_input_id") or 0)
    except (TypeError, ValueError):
        monthly_input_id = 0
    if not monthly_input_id:
        return jsonify({"error": "monthly_input_id is required"}), 400

    monthly = PlazaMonthlyExceptionInput.query.filter_by(
        id=monthly_input_id,
        plaza_identifier=job.plaza_identifier,
        slot="full_exempt_final",
    ).first()
    if monthly is None:
        return jsonify({"error": "Exempt final file not found for this plaza."}), 404

    # Keys that must never be deleted when replacing from_plaza attachments.
    protected_keys = {
        r.s3_key
        for r in PlazaMonthlyExceptionInput.query.filter_by(
            slot="full_exempt_final"
        ).all()
        if r.s3_key
    }

    existing = ExceptionJobFile.query.filter_by(
        job_id=job.id, slot="from_plaza"
    ).all()
    for row in existing:
        if row.s3_key and row.s3_key not in protected_keys:
            try:
                delete_object(row.s3_key)
            except Exception:  # noqa: BLE001
                pass
        db.session.delete(row)

    from app.services.exception_pipeline_service import (
        build_full_exempt_final_display_name,
    )

    plaza_name = (
        job.plaza.plaza_name
        if job.plaza is not None
        else (job.pipeline_plaza_key or job.plaza_identifier)
    )
    stored_name = str(monthly.original_file_name or "").strip()
    if "_Exempt_Final_" in stored_name:
        attach_name = stored_name
    else:
        attach_name = build_full_exempt_final_display_name(
            plaza_name=str(plaza_name or "Plaza"),
            year=int(monthly.year),
            month=int(monthly.month),
            created_at=monthly.created_at,
            suffix=".xlsx",
        )

    attached = ExceptionJobFile(
        job_id=job.id,
        slot="from_plaza",
        original_file_name=attach_name,
        s3_key=monthly.s3_key,
        file_url=monthly.file_url,
        file_size_bytes=monthly.file_size_bytes,
    )
    db.session.add(attached)
    if job.status == "failed":
        job.status = "draft"
        job.error_message = None
        job.progress_message = "Draft — Full Exempt final attached as From-plaza."
    else:
        job.progress_message = "Draft — Full Exempt final attached as From-plaza."
    db.session.commit()
    log_ok(
        f"attached monthly_input_id={monthly.id} "
        f"({monthly.original_file_name}) to job {job.job_uuid} as from_plaza"
    )
    return jsonify({"file": attached.to_dict(), "job": job.to_dict()}), 201


@exception_jobs_bp.post("/<job_uuid>/mark-failed")
def mark_job_failed(job_uuid: str):
    """Stop a queued/running job: kill subprocesses, remove Selenium nodes, mark failed."""
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    if job.status not in {"queued", "running"}:
        return (
            jsonify({"error": f"Job is already {job.status}; nothing to reset."}),
            409,
        )
    from datetime import datetime, timezone

    from app.services.exception_job_worker import stop_job_runtime_resources

    payload = request.get_json(silent=True)
    reason = payload.get("reason") if isinstance(payload, dict) else None
    job.status = "failed"
    job.error_message = (
        str(reason).strip()
        if reason
        else "Marked failed — related processes were stopped."
    )
    job.progress_message = "Marked failed — processes stopped; you can Retry."
    job.finished_at = datetime.now(timezone.utc)
    db.session.commit()

    cleanup = {"killed_children": 0, "removed_chrome_nodes": 0}
    try:
        cleanup = stop_job_runtime_resources()
    except Exception as exc:  # noqa: BLE001
        log_fail(f"mark-failed cleanup error for {job.job_uuid}: {exc}")

    log_ok(
        f"marked exception job {job.job_uuid} failed "
        f"(killed={cleanup.get('killed_children', 0)}, "
        f"chrome_nodes={cleanup.get('removed_chrome_nodes', 0)})"
    )
    return jsonify({"job": job.to_dict(), "cleanup": cleanup})


@exception_jobs_bp.post("/<job_uuid>/resume-interrupted")
def resume_interrupted_job_route(job_uuid: str):
    """Queue a job that was left running when the server closed."""
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    if job.status != "interrupted":
        return (
            jsonify({"error": f"Job is {job.status}; nothing to resume."}),
            409,
        )

    from app.models.exception_pipeline import (
        ExceptionPipelineBatch,
        ExceptionPipelineBatchStep,
    )
    from app.services.exception_job_worker import requeue_interrupted_job
    from app.services.exception_pipeline_service import resume_interrupted_batch

    step = ExceptionPipelineBatchStep.query.filter_by(child_job_uuid=job.job_uuid).first()
    batch = step.batch if step is not None else None
    if batch is None:
        batch = ExceptionPipelineBatch.query.filter_by(
            analytics_job_uuid=job.job_uuid
        ).first()
    if batch is not None and batch.status == "interrupted":
        try:
            resumed = resume_interrupted_batch(batch.batch_uuid)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        db.session.refresh(job)
        return jsonify({"job": job.to_dict(), "batch": resumed.to_dict()})

    requeue_interrupted_job(job)
    db.session.commit()
    log_ok(f"resumed interrupted job {job.job_uuid}")
    return jsonify({"job": job.to_dict()})


@exception_jobs_bp.post("/<job_uuid>/start")
def start_job(job_uuid: str):
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    if job.status not in EDITABLE_STATUSES:
        return (
            jsonify({"error": f"Cannot start job while status is {job.status}."}),
            409,
        )

    program = get_program(job.program_code)
    if program is None or not program.get("enabled"):
        return jsonify({"error": "Program is not enabled"}), 400

    body = request.get_json(silent=True) or {}
    scrape_mode = str(body.get("scrape_mode") or "live").strip().lower()
    if scrape_mode not in {"live", "export"}:
        scrape_mode = "live"

    files_by_slot: dict[str, list] = {}
    for row in job.files:
        files_by_slot.setdefault(row.slot, []).append(row)

    missing = []
    for slot in program["input_slots"]:
        if slot.get("required") and not files_by_slot.get(slot["key"]):
            missing.append(slot["label"])
    if missing:
        return (
            jsonify({"error": "Missing required uploads: " + ", ".join(missing)}),
            400,
        )

    if job.program_code == "full_exempt_e1_e2_e3_e13_e14":
        from app.services.plaza_reference_files import (
            full_exempt_reference_block_reason,
            job_reference_period,
        )

        period_start, period_end = job_reference_period(job)
        block = full_exempt_reference_block_reason(
            plaza_identifier=job.plaza_identifier,
            pipeline_plaza_key=job.pipeline_plaza_key,
            start=period_start,
            end=period_end,
            has_rates_upload=bool(files_by_slot.get("rates")),
            has_approved_upload=bool(files_by_slot.get("approved_exemption")),
        )
        if block:
            return jsonify({"error": block}), 400

    # Analytics (and similar): at least one of several slots must have files.
    any_slots = [
        str(key).strip()
        for key in (program.get("require_any_slots") or [])
        if str(key).strip()
    ]
    if any_slots and not any(files_by_slot.get(key) for key in any_slots):
        labels = []
        for slot in program.get("input_slots") or []:
            if slot.get("key") in any_slots:
                labels.append(slot.get("label") or slot.get("key"))
        return (
            jsonify(
                {
                    "error": (
                        "Upload at least one of: "
                        + ", ".join(labels or any_slots)
                    ),
                }
            ),
            400,
        )

    # When a scrape-capable program has no scraped input, honor scrape_mode
    # (live|export). Default to live so Start still works if the UI omitted it.
    scrape_slot = str(program.get("scrape_slot") or "").strip()
    needs_scrape_choice = bool(
        program.get("may_live_scrape")
        and scrape_slot
        and not files_by_slot.get(scrape_slot)
    )
    mode_for_worker = scrape_mode if needs_scrape_choice else "live"
    if needs_scrape_choice and "scrape_mode" not in body:
        mode_for_worker = "live"

    job.status = "queued"
    job.error_message = None
    # Worker reads scrape mode from memory, process_name |sm=, and this prefix.
    from app.services.exception_job_worker import (
        encode_scrape_mode_on_process_name,
        remember_scrape_mode,
    )

    remember_scrape_mode(job.job_uuid, mode_for_worker)
    encode_scrape_mode_on_process_name(job, mode_for_worker)
    job.progress_message = (
        f"[[scrape_mode={mode_for_worker}]]Queued — waiting for worker…"
    )
    job.started_at = None
    job.finished_at = None
    db.session.commit()
    log_ok(f"queued exception job {job.job_uuid} scrape_mode={mode_for_worker}")
    return jsonify({"job": job.to_dict()})


@exception_jobs_bp.get("/<job_uuid>/files/<int:file_id>/download")
def download_job_file(job_uuid: str, file_id: int):
    """Presigned GET URL for a job file (including scrape_vehicles export)."""
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    row = ExceptionJobFile.query.filter_by(id=file_id, job_id=job.id).first()
    if row is None:
        return jsonify({"error": "File not found"}), 404
    try:
        from app.services.exception_job_s3 import s3_client, bucket_name as _bucket

        client = s3_client()
        url = client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": _bucket(),
                "Key": row.s3_key,
                "ResponseContentDisposition": (
                    f'attachment; filename="{secure_filename(row.original_file_name)}"'
                ),
            },
            ExpiresIn=3600,
        )
    except Exception as exc:  # noqa: BLE001
        log_fail(f"exception job download presign failed: {exc}")
        return jsonify({"error": str(exc)}), 500
    return jsonify(
        {
            "download_url": url,
            "file_name": row.original_file_name,
            "slot": row.slot,
        }
    )


@exception_jobs_bp.get("/<job_uuid>/outputs")
def list_job_outputs(job_uuid: str):
    """Generated files kept on the server when S3 publish is off."""
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    from app.services.exception_job_cleanup import list_local_job_outputs

    return jsonify(
        {
            "files": list_local_job_outputs(job),
            "publish_exception_results": bool(
                Config.PUBLISH_EXCEPTION_RESULTS
            ),
        }
    )


@exception_jobs_bp.get("/<job_uuid>/outputs/download")
def download_job_output(job_uuid: str):
    """Stream one generated output file from the job workspace."""
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    from app.services.exception_job_cleanup import resolve_local_job_output

    relative = str(request.args.get("path") or "").strip()
    try:
        path = resolve_local_job_output(job, relative)
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 400
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    return send_file(path, as_attachment=True, download_name=path.name)
