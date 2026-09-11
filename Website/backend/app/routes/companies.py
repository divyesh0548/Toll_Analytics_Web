"""Company API routes."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from app.extensions import db
from app.models.company import Company
from app.models.company_contact import CompanyContact
from app.models.plaza import Plaza
from app.models.spv import Spv
from app.services.auth_tokens import deny_viewer_writes, get_current_user
from app.utils.api_log import log_fail, log_ok

companies_bp = Blueprint("companies", __name__)


@companies_bp.before_request
def _require_auth():
    if not get_current_user():
        log_fail("companies: auth required")
        return {"error": "Authentication required"}, 401
    denied = deny_viewer_writes()
    if denied:
        log_fail("companies: viewer write blocked")
        return denied


def _apply_company_fields(company: Company, data: dict) -> None:
    mapping = {
        "company_name": "company_name",
        "short_code": "short_code",
        "cin": "cin",
        "pan": "pan",
        "gstin": "gstin",
        "address": "address",
        "state": "state",
        "city": "city",
        "pin": "pin",
        "holding_parent": "holding_parent",
        "auditor": "auditor",
        "financial_year_end": "financial_year_end",
    }
    for src, attr in mapping.items():
        if src in data:
            value = data[src]
            if isinstance(value, str):
                value = value.strip() or None
            if attr in {"company_name", "short_code"} and not value:
                raise ValueError(f"{attr} is required")
            setattr(company, attr, value)


def _sync_contacts(company: Company, contacts_data: list | None) -> None:
    if contacts_data is None:
        return
    company.contacts.clear()
    for item in contacts_data:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        company.contacts.append(
            CompanyContact(
                company_identifier=company.company_identifier,
                name=name,
                email=(item.get("email") or "").strip() or None,
                phone=(item.get("phone") or "").strip() or None,
            )
        )


@companies_bp.get("")
def list_companies():
    companies = Company.query.order_by(Company.company_name.asc()).all()
    spv_counts = dict(
        db.session.query(Spv.company_identifier, func.count(Spv.id))
        .group_by(Spv.company_identifier)
        .all()
    )
    plaza_counts = dict(
        db.session.query(Spv.company_identifier, func.count(Plaza.id))
        .join(Plaza, Plaza.spv_identifier == Spv.spv_identifier)
        .group_by(Spv.company_identifier)
        .all()
    )
    payload = []
    for company in companies:
        item = company.to_dict()
        item["spv_count"] = int(spv_counts.get(company.company_identifier, 0))
        item["plaza_count"] = int(plaza_counts.get(company.company_identifier, 0))
        payload.append(item)
    log_ok(f"listed {len(payload)} companies")
    return jsonify({"companies": payload})


@companies_bp.get("/<company_identifier>")
def get_company(company_identifier: str):
    company = Company.query.filter_by(company_identifier=company_identifier).first_or_404()
    item = company.to_dict()
    item["spv_count"] = (
        db.session.query(func.count(Spv.id))
        .filter_by(company_identifier=company.company_identifier)
        .scalar()
        or 0
    )
    log_ok(f"fetched company {company.company_name}")
    return jsonify(item)


@companies_bp.post("")
def create_company():
    data = request.get_json(silent=True) or {}
    try:
        company = Company()
        _apply_company_fields(company, data)
        if not company.company_name or not company.short_code:
            log_fail("company create failed: missing name/code")
            return jsonify({"error": "company_name and short_code are required"}), 400
        db.session.add(company)
        db.session.flush()
        _sync_contacts(company, data.get("contacts"))
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        log_fail(f"company create failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log_fail(f"company create failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    log_ok(f"{company.company_name} created successfully")
    return jsonify(company.to_dict()), 201


@companies_bp.put("/<company_identifier>")
def update_company(company_identifier: str):
    company = Company.query.filter_by(company_identifier=company_identifier).first_or_404()
    data = request.get_json(silent=True) or {}
    try:
        _apply_company_fields(company, data)
        _sync_contacts(company, data.get("contacts"))
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        log_fail(f"company update failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log_fail(f"company update failed: {exc}")
        return jsonify({"error": str(exc)}), 400
    log_ok(f"{company.company_name} updated successfully")
    return jsonify(company.to_dict())
