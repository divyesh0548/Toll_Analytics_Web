"""Upload plaza rates and approved-exemption files. SNT role only."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from flask import Blueprint, request
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.plaza import Plaza
from app.models.plaza_reference_file import REFERENCE_KINDS, PlazaReferenceFile
from app.services.auth_tokens import get_current_user
from app.services.exception_job_s3 import (
    bucket_name,
    delete_object,
    s3_client,
    upload_reference_stream,
)
from app.services.plaza_reference_files import find_overlap

plaza_reference_files_bp = Blueprint("plaza_reference_files", __name__)

_ALLOWED_SUFFIXES = {".xlsx", ".xls", ".xlsm"}
_KIND_LABELS = {
    "rates": "Rates",
    "approved_exemption": "Approved exemption",
}


@plaza_reference_files_bp.before_request
def _require_snt():
    user = get_current_user()
    if not user:
        return {"error": "Authentication required"}, 401
    if user.role != "snt":
        return {"error": "Forbidden"}, 403
    return None


def _parse_date(value: str, label: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be a date (YYYY-MM-DD)") from exc


@plaza_reference_files_bp.get("")
def list_files():
    plaza_identifier = str(request.args.get("plaza_identifier") or "").strip()
    query = PlazaReferenceFile.query
    if plaza_identifier:
        query = query.filter_by(plaza_identifier=plaza_identifier)
    rows = query.order_by(
        PlazaReferenceFile.kind.asc(),
        PlazaReferenceFile.valid_from.desc(),
        PlazaReferenceFile.id.desc(),
    ).all()
    return {"files": [row.to_dict() for row in rows]}


@plaza_reference_files_bp.post("")
def upload_file():
    plaza_identifier = str(request.form.get("plaza_identifier") or "").strip()
    kind = str(request.form.get("kind") or "").strip()
    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first()
    if plaza is None:
        return {"error": "Select a plaza"}, 400
    if kind not in REFERENCE_KINDS:
        return {"error": "Choose Rates or Approved exemption"}, 400
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return {"error": "Choose a file"}, 400
    original_name = Path(upload.filename).name[:255]
    suffix = Path(original_name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        return {"error": "Upload an Excel file (.xlsx, .xls, or .xlsm)"}, 400
    try:
        valid_from = _parse_date(request.form.get("valid_from"), "Valid from")
        raw_to = str(request.form.get("valid_to") or "").strip()
        valid_to = _parse_date(raw_to, "Valid to") if raw_to else None
    except ValueError as exc:
        return {"error": str(exc)}, 400
    if valid_to is not None and valid_to < valid_from:
        return {"error": "Valid to must be on or after Valid from"}, 400

    overlap = find_overlap(plaza_identifier, kind, valid_from, valid_to)
    replacing = None
    if overlap is not None:
        same_interval = (
            overlap.valid_from == valid_from and overlap.valid_to == valid_to
        )
        if not same_interval:
            end = overlap.valid_to.isoformat() if overlap.valid_to else "open"
            return {
                "error": (
                    f"Those dates overlap {overlap.original_file_name} "
                    f"({overlap.valid_from.isoformat()} to {end}). "
                    "Delete that file, or upload again with the same dates to replace it."
                )
            }, 409
        replacing = overlap

    try:
        stored = upload_reference_stream(
            fileobj=upload.stream,
            plaza_name=plaza.plaza_name,
            kind=kind,
            original_file_name=original_name,
            content_type=upload.mimetype,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not store the file: {exc}"}, 400

    user = get_current_user()
    row = PlazaReferenceFile(
        plaza_identifier=plaza.plaza_identifier,
        kind=kind,
        valid_from=valid_from,
        valid_to=valid_to,
        s3_key=stored["s3_key"],
        original_file_name=original_name,
        file_size_bytes=stored.get("file_size_bytes"),
        uploaded_by_user_id=user.id if user else None,
    )
    old_key = None
    if replacing is not None:
        old_key = replacing.s3_key
        db.session.delete(replacing)
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        try:
            delete_object(stored["s3_key"])
        except Exception:  # noqa: BLE001
            pass
        return {"error": "Could not save the file record"}, 400
    if old_key and old_key != stored["s3_key"]:
        try:
            delete_object(old_key)
        except Exception:  # noqa: BLE001
            pass
    return {"file": row.to_dict(), "label": _KIND_LABELS[kind]}


@plaza_reference_files_bp.get("/<int:file_id>/download")
def download_file(file_id: int):
    row = db.session.get(PlazaReferenceFile, file_id)
    if row is None:
        return {"error": "File not found"}, 404
    file_name = secure_filename(row.original_file_name) or "file.xlsx"
    try:
        url = s3_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket_name(),
                "Key": row.s3_key,
                "ResponseContentDisposition": f'attachment; filename="{file_name}"',
            },
            ExpiresIn=3600,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not prepare the download: {exc}"}, 400
    return {"download_url": url, "file_name": row.original_file_name}


@plaza_reference_files_bp.delete("/<int:file_id>")
def delete_file(file_id: int):
    row = db.session.get(PlazaReferenceFile, file_id)
    if row is None:
        return {"error": "File not found"}, 404
    s3_key = row.s3_key
    db.session.delete(row)
    db.session.commit()
    try:
        delete_object(s3_key)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}
