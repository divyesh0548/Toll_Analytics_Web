"""Plaza API routes."""

from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models.calendar_event import PlazaCalendarEvent
from app.models.plaza import Plaza
from app.models.spv import Spv
from app.services.audit_exceptions import build_plaza_audit_exceptions
from app.services.auth_tokens import deny_viewer_writes, get_current_user
from app.services.calendar_events import (
    bulk_upsert_from_upload,
    create_event,
    delete_event,
    list_events,
    parse_upload,
    update_event,
)
from app.utils.api_log import log_fail, log_ok

plazas_bp = Blueprint("plazas", __name__)


@plazas_bp.before_request
def _require_auth():
    if not get_current_user():
        log_fail("plazas: auth required")
        return {"error": "Authentication required"}, 401
    denied = deny_viewer_writes()
    if denied:
        log_fail("plazas: viewer write blocked")
        return denied


def _parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"Invalid date: {value}") from exc


def _parse_int(value, field_name: str):
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if number < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return number


def _apply_plaza_fields(plaza: Plaza, data: dict) -> None:
    spv_identifier = (data.get("spv_identifier") or "").strip()
    if not spv_identifier:
        raise ValueError("parent SPV is required")
    spv = Spv.query.filter_by(spv_identifier=spv_identifier).first()
    if not spv:
        raise ValueError("selected parent SPV was not found")

    plaza_name = (data.get("plaza_name") or "").strip()
    if not plaza_name:
        raise ValueError("plaza_name is required")

    plaza.spv_identifier = spv_identifier
    plaza.plaza_name = plaza_name
    plaza.plaza_code = (data.get("plaza_code") or "").strip() or None
    plaza.chainage = (data.get("chainage") or "").strip() or None
    plaza.district_state = (data.get("district_state") or "").strip() or None
    plaza.latitude = (data.get("latitude") or "").strip() or None
    plaza.longitude = (data.get("longitude") or "").strip() or None
    plaza.tolling_start_date = _parse_date(data.get("tolling_start_date"))
    plaza.total_lanes = _parse_int(data.get("total_lanes"), "total_lanes")
    plaza.lhs_rhs_split = (data.get("lhs_rhs_split") or "").strip() or None
    plaza.hybrid_etc_only = (data.get("hybrid_etc_only") or "").strip() or None
    plaza.shift_pattern = (data.get("shift_pattern") or "").strip() or None
    plaza.toll_day_cutoff = (data.get("toll_day_cutoff") or "").strip() or None
    plaza.om_contractor = (data.get("om_contractor") or "").strip() or None
    plaza.source_daily_tms_report = (
        (data.get("source_daily_tms_report") or "").strip() or None
    )
    # Free-text event_calendar is deprecated in favor of plaza_calendar_events.
    # Only overwrite when the client still sends the field.
    if "event_calendar" in data:
        plaza.event_calendar = (data.get("event_calendar") or "").strip() or None


@plazas_bp.get("")
def list_plazas():
    spv_identifier = (request.args.get("spv_identifier") or "").strip()
    query = Plaza.query
    if spv_identifier:
        query = query.filter_by(spv_identifier=spv_identifier)
    plazas = query.order_by(Plaza.plaza_name.asc()).all()
    log_ok(f"listed {len(plazas)} plazas")
    return jsonify({"plazas": [p.to_dict() for p in plazas]})


@plazas_bp.get("/<plaza_identifier>")
def get_plaza(plaza_identifier: str):
    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first_or_404()
    log_ok(f"fetched plaza {plaza.plaza_name}")
    return jsonify(plaza.to_dict())


@plazas_bp.get("/<plaza_identifier>/audit-exceptions")
def plaza_audit_exceptions(plaza_identifier: str):
    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first_or_404()
    year_raw = (request.args.get("year") or "").strip()
    month_raw = (request.args.get("month") or "").strip()
    try:
        year = int(year_raw) if year_raw else None
        month = int(month_raw) if month_raw else None
    except ValueError:
        log_fail("audit exceptions: invalid year/month")
        return jsonify({"error": "year and month must be integers"}), 400
    try:
        payload = build_plaza_audit_exceptions(
            plaza.plaza_identifier,
            year=year,
            month=month,
        )
    except ValueError as exc:
        log_fail(f"audit exceptions failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        log_fail(f"audit exceptions failed: {exc}")
        return jsonify({"error": str(exc)}), 500

    payload["plaza"] = {
        "plaza_identifier": plaza.plaza_identifier,
        "plaza_name": plaza.plaza_name,
        "plaza_code": plaza.plaza_code,
    }
    log_ok(
        f"audit exceptions for {plaza.plaza_name} "
        f"({payload['selection']['label']})"
    )
    return jsonify(payload)


@plazas_bp.get("/<plaza_identifier>/calendar-events")
def plaza_calendar_events(plaza_identifier: str):
    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first_or_404()
    start_raw = (request.args.get("start") or "").strip()
    end_raw = (request.args.get("end") or "").strip()
    type_raw = (request.args.get("event_type") or "").strip()
    try:
        start = _parse_date(start_raw) if start_raw else None
        end = _parse_date(end_raw) if end_raw else None
        event_types = [t.strip() for t in type_raw.split(",") if t.strip()] or None
        events = list_events(
            plaza.plaza_identifier,
            start=start,
            end=end,
            event_types=event_types,
        )
    except ValueError as exc:
        log_fail(f"calendar events list failed: {exc}")
        return jsonify({"error": str(exc)}), 400

    log_ok(f"listed {len(events)} calendar events for {plaza.plaza_name}")
    return jsonify(
        {
            "plaza": {
                "plaza_identifier": plaza.plaza_identifier,
                "plaza_name": plaza.plaza_name,
            },
            "events": [e.to_dict() for e in events],
        }
    )


@plazas_bp.post("/<plaza_identifier>/calendar-events")
def create_plaza_calendar_event(plaza_identifier: str):
    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first_or_404()
    data = request.get_json(silent=True) or {}
    try:
        event = create_event(plaza.plaza_identifier, data)
    except ValueError as exc:
        log_fail(f"calendar event create failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log_fail(f"calendar event create failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    log_ok(f"calendar event created for {plaza.plaza_name}: {event.label}")
    return jsonify(event.to_dict()), 201


@plazas_bp.patch("/<plaza_identifier>/calendar-events/<int:event_id>")
def update_plaza_calendar_event(plaza_identifier: str, event_id: int):
    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first_or_404()
    event = PlazaCalendarEvent.query.filter_by(
        id=event_id,
        plaza_identifier=plaza.plaza_identifier,
    ).first_or_404()
    data = request.get_json(silent=True) or {}
    try:
        updated = update_event(event, data)
    except ValueError as exc:
        log_fail(f"calendar event update failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log_fail(f"calendar event update failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    log_ok(f"calendar event updated for {plaza.plaza_name}: {updated.label}")
    return jsonify(updated.to_dict())


@plazas_bp.delete("/<plaza_identifier>/calendar-events/<int:event_id>")
def delete_plaza_calendar_event(plaza_identifier: str, event_id: int):
    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first_or_404()
    event = PlazaCalendarEvent.query.filter_by(
        id=event_id,
        plaza_identifier=plaza.plaza_identifier,
    ).first_or_404()
    label = event.label
    try:
        delete_event(event)
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log_fail(f"calendar event delete failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    log_ok(f"calendar event deleted for {plaza.plaza_name}: {label}")
    return jsonify({"ok": True})


@plazas_bp.post("/<plaza_identifier>/calendar-events/upload")
def upload_plaza_calendar_events(plaza_identifier: str):
    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first_or_404()
    file_storage = request.files.get("file")
    try:
        rows, parse_errors = parse_upload(file_storage)
        result = bulk_upsert_from_upload(plaza.plaza_identifier, rows)
    except ValueError as exc:
        log_fail(f"calendar upload failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log_fail(f"calendar upload failed: {exc}")
        return jsonify({"error": str(exc)}), 400

    log_ok(
        f"calendar upload for {plaza.plaza_name}: "
        f"created={result['created']} skipped={result['skipped']} "
        f"errors={len(parse_errors)}"
    )
    return jsonify(
        {
            "created": result["created"],
            "skipped": result["skipped"],
            "errors": parse_errors,
            "parsed": len(rows),
        }
    )


@plazas_bp.post("")
def create_plaza():
    data = request.get_json(silent=True) or {}
    plaza = Plaza()
    try:
        _apply_plaza_fields(plaza, data)
        db.session.add(plaza)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        log_fail(f"plaza create failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log_fail(f"plaza create failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    log_ok(f"{plaza.plaza_name} created successfully")
    return jsonify(plaza.to_dict()), 201


@plazas_bp.put("/<plaza_identifier>")
def update_plaza(plaza_identifier: str):
    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first_or_404()
    data = request.get_json(silent=True) or {}
    try:
        _apply_plaza_fields(plaza, data)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        log_fail(f"plaza update failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log_fail(f"plaza update failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    log_ok(f"{plaza.plaza_name} updated successfully")
    return jsonify(plaza.to_dict())
