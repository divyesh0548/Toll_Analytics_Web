"""SPV API routes."""

from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models.company import Company
from app.models.spv import Spv
from app.services.auth_tokens import get_current_user

spvs_bp = Blueprint("spvs", __name__)


@spvs_bp.before_request
def _require_auth():
    if not get_current_user():
        return {"error": "Authentication required"}, 401


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


def _parse_decimal(value, field_name: str):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc


def _apply_spv_fields(spv: Spv, data: dict) -> None:
    company_identifier = (data.get("company_identifier") or "").strip()
    if not company_identifier:
        raise ValueError("parent company is required")
    company = Company.query.filter_by(company_identifier=company_identifier).first()
    if not company:
        raise ValueError("selected parent company was not found")

    spv_name = (data.get("spv_name") or "").strip()
    if not spv_name:
        raise ValueError("spv_name is required")

    spv.company_identifier = company_identifier
    spv.spv_name = spv_name
    spv.project_stretch_name = (data.get("project_stretch_name") or "").strip() or None
    spv.nh_no = (data.get("nh_no") or "").strip() or None
    spv.chainage_from = (data.get("chainage_from") or "").strip() or None
    spv.chainage_to = (data.get("chainage_to") or "").strip() or None
    spv.length_km = _parse_int(data.get("length_km"), "length_km")
    spv.rate_notification_no_date = (
        (data.get("rate_notification_no_date") or "").strip() or None
    )
    spv.annual_revision_pct = _parse_decimal(
        data.get("annual_revision_pct"), "annual_revision_pct"
    )
    spv.wpi_linkage = (data.get("wpi_linkage") or "").strip() or None
    spv.effective_from = _parse_date(data.get("effective_from"))
    spv.rate_card_upload = (data.get("rate_card_upload") or "").strip() or None
    spv.exempt_categories_policy = (
        (data.get("exempt_categories_policy") or "").strip() or None
    )
    spv.local_monthly_pass_rules = (
        (data.get("local_monthly_pass_rules") or "").strip() or None
    )
    spv.lead_bank_lender = (data.get("lead_bank_lender") or "").strip() or None
    spv.facility_limit = (data.get("facility_limit") or "").strip() or None
    spv.escrow_bank = (data.get("escrow_bank") or "").strip() or None
    spv.revenue_share_premium_pct = _parse_decimal(
        data.get("revenue_share_premium_pct"), "revenue_share_premium_pct"
    )
    spv.premium_escalation = (data.get("premium_escalation") or "").strip() or None


@spvs_bp.get("")
def list_spvs():
    company_identifier = (request.args.get("company_identifier") or "").strip()
    query = Spv.query
    if company_identifier:
        query = query.filter_by(company_identifier=company_identifier)
    spvs = query.order_by(Spv.spv_name.asc()).all()
    return jsonify({"spvs": [s.to_dict() for s in spvs]})


@spvs_bp.get("/<spv_identifier>")
def get_spv(spv_identifier: str):
    spv = Spv.query.filter_by(spv_identifier=spv_identifier).first_or_404()
    return jsonify(spv.to_dict())


@spvs_bp.post("")
def create_spv():
    data = request.get_json(silent=True) or {}
    spv = Spv()
    try:
        _apply_spv_fields(spv, data)
        db.session.add(spv)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    return jsonify(spv.to_dict()), 201


@spvs_bp.put("/<spv_identifier>")
def update_spv(spv_identifier: str):
    spv = Spv.query.filter_by(spv_identifier=spv_identifier).first_or_404()
    data = request.get_json(silent=True) or {}
    try:
        _apply_spv_fields(spv, data)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    return jsonify(spv.to_dict())
