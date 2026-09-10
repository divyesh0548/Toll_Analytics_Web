"""Plaza API routes."""

from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models.plaza import Plaza
from app.models.spv import Spv
from app.services.auth_tokens import deny_viewer_writes, get_current_user
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
