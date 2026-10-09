"""Exception processing job APIs (programs catalog + upload + start)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.audit_exception import AuditExceptionOutputFile
from app.models.exception_job import ExceptionJob, ExceptionJobFile
from app.models.plaza import Plaza
from app.services.auth_tokens import deny_viewer_writes, get_current_user
from app.services.exception_job_s3 import delete_object, upload_bytes
from app.services.exception_program_catalog import (
    get_program,
    job_list_codes_for_program,
    list_programs,
    load_annexure_server_defaults,
    load_pipeline_plaza_keys,
)
from app.services.plaza_entity_map import resolve_entity_name
from app.utils.api_log import log_fail, log_ok

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
    """Server-side default rates / approved exemption for a pipeline plaza key."""
    plaza_key = (request.args.get("pipeline_plaza_key") or "").strip().upper()
    if not plaza_key:
        return jsonify({"error": "pipeline_plaza_key is required"}), 400
    defaults = load_annexure_server_defaults(plaza_key)
    log_ok(f"annexure defaults for {plaza_key}")
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


@exception_jobs_bp.post("/<job_uuid>/files")
def upload_job_file(job_uuid: str):
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    if job.status not in EDITABLE_STATUSES:
        return (
            jsonify({"error": f"Cannot upload while job status is {job.status}."}),
            409,
        )

    program = get_program(job.program_code)
    if program is None:
        return jsonify({"error": "Program missing from catalog"}), 500

    slot = (request.form.get("slot") or "").strip()
    slot_cfg = next((s for s in program["input_slots"] if s["key"] == slot), None)
    if slot_cfg is None:
        return jsonify({"error": f"Invalid slot: {slot}"}), 400

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "file is required"}), 400

    original_name = secure_filename(upload.filename) or "upload.bin"
    body = upload.read()
    if not body:
        return jsonify({"error": "Uploaded file is empty"}), 400

    # Single-file slots: replace previous object(s)
    if not slot_cfg.get("multiple"):
        existing = ExceptionJobFile.query.filter_by(job_id=job.id, slot=slot).all()
        for row in existing:
            try:
                delete_object(row.s3_key)
            except Exception:  # noqa: BLE001
                pass
            db.session.delete(row)
        db.session.commit()

    plaza = job.plaza
    plaza_name = plaza.plaza_name if plaza else job.pipeline_plaza_key
    try:
        uploaded = upload_bytes(
            body=body,
            plaza_name=plaza_name,
            job_uuid=job.job_uuid,
            slot=slot,
            original_file_name=original_name,
            content_type=upload.mimetype,
        )
    except Exception as exc:  # noqa: BLE001
        log_fail(f"exception job upload failed: {exc}")
        return jsonify({"error": str(exc)}), 500

    row = ExceptionJobFile(
        job_id=job.id,
        slot=slot,
        original_file_name=original_name,
        s3_key=uploaded["s3_key"],
        file_url=uploaded["file_url"],
        file_size_bytes=uploaded["file_size_bytes"],
    )
    db.session.add(row)
    if job.status == "failed":
        job.status = "draft"
        job.error_message = None
        job.progress_message = "Draft — files updated after failure."
    db.session.commit()
    log_ok(f"uploaded {original_name} to job {job.job_uuid} slot={slot}")
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
    if s3_key:
        staging_rows = (
            AuditExceptionOutputFile.query.filter_by(
                s3_key=s3_key,
                is_final_output=False,
            ).all()
        )

    # Failed jobs: hard-delete S3 + any staging output-file DB row.
    # Draft + staging attach: only detach from the job (keep staging for reuse).
    # Draft + normal upload: delete the uploaded S3 object.
    hard_delete_s3 = job.status == "failed" or not staging_rows
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
        f"staging_rows={len(staging_rows)})"
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


@exception_jobs_bp.post("/<job_uuid>/mark-failed")
def mark_job_failed(job_uuid: str):
    """Unstick a job left as queued/running after a crash or forced stop."""
    job = ExceptionJob.query.filter_by(job_uuid=job_uuid).first()
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    if job.status not in {"queued", "running"}:
        return (
            jsonify({"error": f"Job is already {job.status}; nothing to reset."}),
            409,
        )
    from datetime import datetime, timezone

    job.status = "failed"
    job.error_message = (
        str(request.get_json(silent=True) or {}).get("reason")
        or "Marked failed manually (process was not actually running)."
    )
    job.progress_message = "Marked failed — you can Retry."
    job.finished_at = datetime.now(timezone.utc)
    db.session.commit()
    log_ok(f"marked exception job {job.job_uuid} failed")
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

    job.status = "queued"
    job.error_message = None
    job.progress_message = "Queued — waiting for worker…"
    job.started_at = None
    job.finished_at = None
    db.session.commit()
    log_ok(f"queued exception job {job.job_uuid}")
    return jsonify({"job": job.to_dict()})
