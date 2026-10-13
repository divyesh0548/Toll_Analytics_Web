"""Monthly exception inputs + one-click pipeline batch APIs."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models.exception_pipeline import (
    ExceptionPipelineBatch,
    PlazaMonthlyExceptionInput,
)
from app.models.plaza import Plaza
from app.services.auth_tokens import deny_viewer_writes, get_current_user
from app.services.exception_job_s3 import (
    delete_object,
    head_object_size,
    monthly_input_key_prefix,
    presign_monthly_put_upload,
)
from app.services.exception_pipeline_service import (
    cancel_batch,
    create_batch,
    period_status,
    start_batch,
)
from app.services.exception_program_catalog import (
    load_pipeline_plaza_keys,
    load_plaza_identifier_to_pipeline_key,
)
from app.services.pipeline_dependency_catalog import (
    list_monthly_input_slots,
    list_pipeline_programs,
)
from app.utils.api_log import log_fail, log_ok

exception_pipeline_bp = Blueprint("exception_pipeline", __name__)

_USER_SLOTS = {s["key"] for s in list_monthly_input_slots(include_system=False)}


@exception_pipeline_bp.before_request
def _require_auth():
    if not get_current_user():
        log_fail("exception_pipeline: auth required")
        return {"error": "Authentication required"}, 401
    denied = deny_viewer_writes()
    if denied:
        log_fail("exception_pipeline: viewer write blocked")
        return denied


@exception_pipeline_bp.get("/catalog")
def pipeline_catalog():
    log_ok("exception pipeline catalog")
    return jsonify(
        {
            "input_slots": list_monthly_input_slots(include_system=True),
            "programs": list_pipeline_programs(),
            "pipeline_plaza_keys": load_pipeline_plaza_keys(),
            "plaza_identifier_to_pipeline_key": load_plaza_identifier_to_pipeline_key(),
        }
    )


@exception_pipeline_bp.get("/period")
def get_period():
    plaza_identifier = (request.args.get("plaza_identifier") or "").strip()
    try:
        year = int(request.args.get("year") or 0)
        month = int(request.args.get("month") or 0)
    except ValueError:
        return jsonify({"error": "year and month must be integers"}), 400
    if not plaza_identifier:
        return jsonify({"error": "plaza_identifier is required"}), 400
    if not (1990 <= year <= 2100 and 1 <= month <= 12):
        return jsonify({"error": "Invalid year/month"}), 400
    if Plaza.query.filter_by(plaza_identifier=plaza_identifier).first() is None:
        return jsonify({"error": "Plaza not found"}), 404
    log_ok(f"pipeline period {plaza_identifier} {year}-{month:02d}")
    return jsonify(period_status(plaza_identifier, year, month))


@exception_pipeline_bp.post("/inputs/presign")
def presign_monthly_input():
    body = request.get_json(silent=True) or {}
    plaza_identifier = str(body.get("plaza_identifier") or "").strip()
    slot = str(body.get("slot") or "").strip()
    file_name = str(body.get("file_name") or "").strip()
    content_type = str(body.get("content_type") or "").strip() or None
    try:
        year = int(body.get("year") or 0)
        month = int(body.get("month") or 0)
        file_size = int(body.get("file_size_bytes") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "year, month, file_size_bytes must be integers"}), 400

    if not plaza_identifier or slot not in _USER_SLOTS:
        return jsonify({"error": "plaza_identifier and a user-upload slot are required"}), 400
    if not (1990 <= year <= 2100 and 1 <= month <= 12):
        return jsonify({"error": "Invalid year/month"}), 400
    if not file_name or file_size <= 0:
        return jsonify({"error": "file_name and file_size_bytes are required"}), 400

    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first()
    if plaza is None:
        return jsonify({"error": "Plaza not found"}), 404

    signed = presign_monthly_put_upload(
        plaza_name=plaza.plaza_name or plaza_identifier,
        year=year,
        month=month,
        slot=slot,
        original_file_name=file_name,
        content_type=content_type,
    )
    log_ok(f"pipeline input presign {plaza_identifier} {year}-{month:02d} slot={slot}")
    return jsonify(
        {
            **signed,
            "plaza_identifier": plaza_identifier,
            "year": year,
            "month": month,
            "slot": slot,
            "original_file_name": file_name,
            "file_size_bytes": file_size,
        }
    )


@exception_pipeline_bp.post("/inputs/complete")
def complete_monthly_input():
    body = request.get_json(silent=True) or {}
    plaza_identifier = str(body.get("plaza_identifier") or "").strip()
    slot = str(body.get("slot") or "").strip()
    s3_key = str(body.get("s3_key") or "").strip()
    file_url = str(body.get("file_url") or "").strip()
    original_file_name = str(body.get("original_file_name") or "").strip()
    content_type = str(body.get("content_type") or "").strip() or None
    try:
        year = int(body.get("year") or 0)
        month = int(body.get("month") or 0)
        file_size = int(body.get("file_size_bytes") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "year, month, file_size_bytes must be integers"}), 400

    if not plaza_identifier or slot not in _USER_SLOTS:
        return jsonify({"error": "plaza_identifier and a user-upload slot are required"}), 400
    if not s3_key or not original_file_name:
        return jsonify({"error": "s3_key and original_file_name are required"}), 400

    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first()
    if plaza is None:
        return jsonify({"error": "Plaza not found"}), 404

    allowed = monthly_input_key_prefix(
        plaza_name=plaza.plaza_name or plaza_identifier,
        year=year,
        month=month,
    )
    if not s3_key.startswith(allowed):
        return jsonify({"error": "s3_key does not belong to this plaza/period"}), 400

    size = head_object_size(s3_key)
    if size is None:
        return jsonify({"error": "S3 object not found after upload"}), 400

    row = PlazaMonthlyExceptionInput(
        plaza_identifier=plaza_identifier,
        year=year,
        month=month,
        slot=slot,
        original_file_name=original_file_name,
        s3_key=s3_key,
        file_url=file_url
        or f"s3://{s3_key}",
        file_size_bytes=size if size is not None else file_size,
        content_type=content_type,
        source="upload",
    )
    db.session.add(row)
    db.session.commit()
    log_ok(f"pipeline input complete id={row.id} slot={slot}")
    return jsonify({"file": row.to_dict(), "period": period_status(plaza_identifier, year, month)})


@exception_pipeline_bp.delete("/inputs/<int:file_id>")
def delete_monthly_input(file_id: int):
    row = PlazaMonthlyExceptionInput.query.get(file_id)
    if row is None:
        return jsonify({"error": "File not found"}), 404
    if row.source == "pipeline_output":
        return jsonify({"error": "System-produced files cannot be deleted here"}), 409
    plaza_identifier = row.plaza_identifier
    year, month = row.year, row.month
    s3_key = row.s3_key
    db.session.delete(row)
    db.session.commit()
    if s3_key:
        try:
            delete_object(s3_key)
        except Exception:  # noqa: BLE001
            pass
    log_ok(f"pipeline input deleted id={file_id}")
    return jsonify({"ok": True, "period": period_status(plaza_identifier, year, month)})


@exception_pipeline_bp.post("/batches")
def create_pipeline_batch():
    body = request.get_json(silent=True) or {}
    plaza_identifier = str(body.get("plaza_identifier") or "").strip()
    pipeline_plaza_key = str(body.get("pipeline_plaza_key") or "").strip() or None
    codes = body.get("program_codes") or []
    if not isinstance(codes, list):
        return jsonify({"error": "program_codes must be a list"}), 400
    # Empty list is allowed when VRN/ETC are present (analytics-only batch).
    try:
        year = int(body.get("year") or 0)
        month = int(body.get("month") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "year and month must be integers"}), 400
    continue_on_failure = bool(body.get("continue_on_failure", True))
    run_analytics = bool(body.get("run_analytics", True))
    user = get_current_user()
    try:
        batch = create_batch(
            plaza_identifier=plaza_identifier,
            year=year,
            month=month,
            program_codes=[str(c).strip() for c in codes if str(c).strip()],
            pipeline_plaza_key=pipeline_plaza_key,
            continue_on_failure=continue_on_failure,
            run_analytics=run_analytics,
            created_by_user_id=getattr(user, "id", None),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    log_ok(f"pipeline batch created {batch.batch_uuid}")
    return jsonify({"batch": batch.to_dict()}), 201


@exception_pipeline_bp.post("/batches/<batch_uuid>/start")
def start_pipeline_batch(batch_uuid: str):
    body = request.get_json(silent=True) or {}
    run_analytics = bool(body.get("run_analytics", True))
    try:
        batch = start_batch(batch_uuid, run_analytics=run_analytics)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    log_ok(f"pipeline batch started {batch_uuid} analytics={run_analytics}")
    return jsonify({"batch": batch.to_dict()})


@exception_pipeline_bp.post("/batches/<batch_uuid>/stop")
def stop_pipeline_batch(batch_uuid: str):
    try:
        batch = cancel_batch(batch_uuid)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    log_ok(f"pipeline batch stopped {batch_uuid}")
    return jsonify({"batch": batch.to_dict()})


@exception_pipeline_bp.get("/batches/<batch_uuid>")
def get_pipeline_batch(batch_uuid: str):
    batch = ExceptionPipelineBatch.query.filter_by(batch_uuid=batch_uuid).first()
    if batch is None:
        return jsonify({"error": "Batch not found"}), 404
    return jsonify({"batch": batch.to_dict()})


@exception_pipeline_bp.get("/batches")
def list_pipeline_batches():
    plaza_identifier = (request.args.get("plaza_identifier") or "").strip()
    q = ExceptionPipelineBatch.query
    if plaza_identifier:
        q = q.filter_by(plaza_identifier=plaza_identifier)
    rows = q.order_by(ExceptionPipelineBatch.id.desc()).limit(50).all()
    return jsonify({"batches": [b.to_dict() for b in rows]})
