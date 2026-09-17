"""Analytics API for Numbers dashboard and portfolio volume."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.models.company import Company
from app.models.plaza import Plaza
from app.services.auth_tokens import get_current_user
from app.services.numbers_analytics import (
    build_plaza_numbers,
    build_portfolio_rollup,
    build_portfolio_volume,
)
from app.utils.api_log import log_fail, log_ok

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.before_request
def _require_auth():
    if not get_current_user():
        log_fail("analytics: auth required")
        return {"error": "Authentication required"}, 401


@analytics_bp.get("/plazas/<plaza_identifier>/numbers")
def plaza_numbers(plaza_identifier: str):
    plaza = Plaza.query.filter_by(plaza_identifier=plaza_identifier).first()
    if not plaza:
        log_fail(f"analytics numbers: plaza not found {plaza_identifier}")
        return jsonify({"error": "Plaza not found"}), 404

    period = (request.args.get("period") or "mtd").strip().lower()
    if period not in {"day", "mtd", "ytd"}:
        period = "mtd"

    start = (request.args.get("start") or "").strip() or None
    end = (request.args.get("end") or "").strip() or None

    try:
        payload = build_plaza_numbers(
            plaza_identifier,
            period,
            start=start,
            end=end,
        )
    except Exception as exc:  # noqa: BLE001
        log_fail(f"analytics numbers failed: {exc}")
        return jsonify({"error": str(exc)}), 500

    payload["plaza"] = {
        "plaza_identifier": plaza.plaza_identifier,
        "plaza_name": plaza.plaza_name,
        "plaza_code": plaza.plaza_code,
    }
    log_ok(f"numbers for {plaza.plaza_name} ({period})")
    return jsonify(payload)


@analytics_bp.get("/portfolio/volume")
def portfolio_volume():
    companies = Company.query.order_by(Company.company_name.asc()).all()
    company_dicts = [
        {
            "company_identifier": c.company_identifier,
            "company_name": c.company_name,
        }
        for c in companies
    ]
    try:
        payload = build_portfolio_volume(company_dicts, years=5)
    except Exception as exc:  # noqa: BLE001
        log_fail(f"portfolio volume failed: {exc}")
        return jsonify({"error": str(exc)}), 500

    log_ok(f"portfolio volume for {len(company_dicts)} companies")
    return jsonify(payload)


@analytics_bp.get("/portfolio/rollup")
def portfolio_rollup():
    companies = Company.query.order_by(Company.company_name.asc()).all()
    company_dicts = [
        {
            "company_identifier": c.company_identifier,
            "company_name": c.company_name,
        }
        for c in companies
    ]
    try:
        payload = build_portfolio_rollup(company_dicts)
    except Exception as exc:  # noqa: BLE001
        log_fail(f"portfolio rollup failed: {exc}")
        return jsonify({"error": str(exc)}), 500

    log_ok(f"portfolio rollup for {len(company_dicts)} companies ({payload.get('year')})")
    return jsonify(payload)
