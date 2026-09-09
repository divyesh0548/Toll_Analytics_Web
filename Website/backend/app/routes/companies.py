"""Company API routes."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models.company import Company
from app.models.company_contact import CompanyContact

companies_bp = Blueprint("companies", __name__)


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
    return jsonify({"companies": [c.to_dict() for c in companies]})


@companies_bp.get("/<company_identifier>")
def get_company(company_identifier: str):
    company = Company.query.filter_by(company_identifier=company_identifier).first_or_404()
    return jsonify(company.to_dict())


@companies_bp.post("")
def create_company():
    data = request.get_json(silent=True) or {}
    try:
        company = Company()
        _apply_company_fields(company, data)
        if not company.company_name or not company.short_code:
            return jsonify({"error": "company_name and short_code are required"}), 400
        db.session.add(company)
        db.session.flush()
        _sync_contacts(company, data.get("contacts"))
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
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
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    return jsonify(company.to_dict())
