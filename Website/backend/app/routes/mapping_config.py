"""Read and edit shared mapping config. SNT role only."""

from __future__ import annotations

from flask import Blueprint, request

from app.extensions import db
from app.models.mapping_config import (
    MappingAlias,
    MappingAudit,
    MappingCanonical,
    MappingDomain,
    MappingListItem,
    MappingSetting,
)
from app.services.auth_tokens import get_current_user
from app.services.mapping_config_seed import normalize_alias

mapping_config_bp = Blueprint("mapping_config", __name__)

DOMAIN_LABELS = {
    "vehicle_class": "Vehicle class",
    "mop": "Mode of payment",
    "column_alias": "Column headers",
    "header_keyword": "Header keywords",
    "tc_index": "TC class index",
    "journey_type": "Journey type",
    "pass_type": "Pass type",
}

LIST_LABELS = {
    "exclude": "Exclude",
    "ignore": "Ignore",
}

ALLOWED_LISTS = {
    "vehicle_class": ("exclude",),
    "mop": ("ignore",),
}

SETTING_LABELS = {
    "header_scan_rows": "Header scan rows",
    "min_header_matches": "Minimum header matches",
    "overrides_by_source": "Header match overrides by source",
}

COLUMN_LABELS = {
    "vehicle_reg_no": "Vehicle registration number",
    "transaction_date": "Transaction date",
    "transaction_time": "Transaction time",
    "transaction_datetime": "Transaction date and time",
    "toll_amount": "Toll amount",
    "vehicle_class": "Vehicle class",
    "journey_type": "Journey type",
    "pass_type": "Pass type",
    "mode_of_payment": "Mode of payment",
    "plaza_code": "Plaza code",
    "lane": "Lane",
    "tag_id": "Tag ID",
    "transaction_id": "Transaction ID",
}


def _label_for_key(key: str) -> str:
    if key in COLUMN_LABELS:
        return COLUMN_LABELS[key]
    text = str(key or "").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else key


def _audit(domain_code: str, action: str, before, after) -> None:
    user = get_current_user()
    db.session.add(
        MappingAudit(
            user_id=user.id if user else None,
            domain_code=domain_code,
            action=action,
            before_json=before,
            after_json=after,
        )
    )


def _domain_for_canonical(canonical: MappingCanonical) -> MappingDomain:
    domain = canonical.domain or db.session.get(MappingDomain, canonical.domain_id)
    if domain is None:
        raise LookupError("domain")
    return domain


def _snapshot() -> dict:
    domains = MappingDomain.query.order_by(MappingDomain.sort_order, MappingDomain.code).all()
    payload_domains = []
    for domain in domains:
        canonicals = (
            MappingCanonical.query.filter_by(domain_id=domain.id, is_active=True)
            .order_by(MappingCanonical.sort_order, MappingCanonical.canonical_key)
            .all()
        )
        groups = []
        for canonical in canonicals:
            aliases = (
                MappingAlias.query.filter_by(canonical_id=canonical.id, is_active=True)
                .order_by(MappingAlias.alias)
                .all()
            )
            groups.append(
                {
                    "id": canonical.id,
                    "key": canonical.canonical_key,
                    "label": _label_for_key(canonical.canonical_key),
                    "db_column": canonical.db_column,
                    "notes": canonical.notes,
                    "aliases": [{"id": alias.id, "alias": alias.alias} for alias in aliases],
                }
            )
        items = (
            MappingListItem.query.filter_by(domain_id=domain.id, is_active=True)
            .order_by(MappingListItem.list_key, MappingListItem.value)
            .all()
        )
        lists: dict[str, list] = {}
        for list_key in ALLOWED_LISTS.get(domain.code, ()):
            lists.setdefault(list_key, [])
        for item in items:
            lists.setdefault(item.list_key, []).append({"id": item.id, "value": item.value})
        payload_domains.append(
            {
                "code": domain.code,
                "label": DOMAIN_LABELS.get(domain.code, domain.label or _label_for_key(domain.code)),
                "lists": [
                    {
                        "list_key": list_key,
                        "label": LIST_LABELS.get(list_key, _label_for_key(list_key)),
                        "items": rows,
                    }
                    for list_key, rows in lists.items()
                ],
                "groups": groups,
            }
        )
    settings = MappingSetting.query.order_by(MappingSetting.key).all()
    return {
        "domains": payload_domains,
        "settings": [
            {
                "key": row.key,
                "label": SETTING_LABELS.get(row.key, _label_for_key(row.key)),
                "value": row.value_json,
            }
            for row in settings
        ],
    }


@mapping_config_bp.before_request
def _require_snt():
    user = get_current_user()
    if not user:
        return {"error": "Authentication required"}, 401
    if user.role != "snt":
        return {"error": "Forbidden"}, 403
    return None


@mapping_config_bp.get("")
def get_mapping_config():
    return _snapshot()


@mapping_config_bp.post("/canonicals/<int:canonical_id>/aliases")
def add_alias(canonical_id: int):
    canonical = db.session.get(MappingCanonical, canonical_id)
    if not canonical or not canonical.is_active:
        return {"error": "Group not found"}, 404
    domain = _domain_for_canonical(canonical)
    body = request.get_json(silent=True) or {}
    alias = str(body.get("alias") or "").strip()
    if not alias:
        return {"error": "Alias is required"}, 400
    normalized = normalize_alias(alias)
    existing = MappingAlias.query.filter_by(
        domain_id=canonical.domain_id,
        alias_normalized=normalized,
    ).first()
    if existing and existing.is_active:
        return {"error": "That value is already stored"}, 409
    if existing:
        before = {"alias": existing.alias, "is_active": False}
        existing.alias = alias
        existing.alias_normalized = normalized
        existing.canonical_id = canonical.id
        existing.is_active = True
        _audit(domain.code, "restore_alias", before, {"alias": alias, "group": canonical.canonical_key})
    else:
        row = MappingAlias(
            domain_id=canonical.domain_id,
            canonical_id=canonical.id,
            alias=alias,
            alias_normalized=normalized,
            is_active=True,
        )
        db.session.add(row)
        db.session.flush()
        _audit(
            domain.code,
            "add_alias",
            None,
            {"alias": alias, "group": canonical.canonical_key},
        )
    db.session.commit()
    return _snapshot()


@mapping_config_bp.patch("/aliases/<int:alias_id>")
def update_alias(alias_id: int):
    row = db.session.get(MappingAlias, alias_id)
    if not row or not row.is_active:
        return {"error": "Alias not found"}, 404
    body = request.get_json(silent=True) or {}
    alias = str(body.get("alias") or "").strip()
    if not alias:
        return {"error": "Alias is required"}, 400
    normalized = normalize_alias(alias)
    clash = MappingAlias.query.filter(
        MappingAlias.domain_id == row.domain_id,
        MappingAlias.alias_normalized == normalized,
        MappingAlias.id != row.id,
    ).first()
    if clash:
        return {"error": "That value is already stored"}, 409
    domain = _domain_for_canonical(row.canonical)
    before = {"alias": row.alias, "group": row.canonical.canonical_key}
    row.alias = alias
    row.alias_normalized = normalized
    _audit(domain.code, "update_alias", before, {"alias": alias, "group": row.canonical.canonical_key})
    db.session.commit()
    return _snapshot()


@mapping_config_bp.delete("/aliases/<int:alias_id>")
def delete_alias(alias_id: int):
    row = db.session.get(MappingAlias, alias_id)
    if not row or not row.is_active:
        return {"error": "Alias not found"}, 404
    domain = _domain_for_canonical(row.canonical)
    before = {"alias": row.alias, "group": row.canonical.canonical_key}
    row.is_active = False
    _audit(domain.code, "remove_alias", before, {"is_active": False})
    db.session.commit()
    return _snapshot()


@mapping_config_bp.post("/domains/<string:domain_code>/lists/<string:list_key>")
def add_list_item(domain_code: str, list_key: str):
    domain = MappingDomain.query.filter_by(code=domain_code).first()
    if not domain:
        return {"error": "Config section not found"}, 404
    allowed = ALLOWED_LISTS.get(domain.code, ())
    known = MappingListItem.query.filter_by(domain_id=domain.id, list_key=list_key).first()
    if list_key not in allowed and not known:
        return {"error": "List not found"}, 404
    body = request.get_json(silent=True) or {}
    value = str(body.get("value") or "").strip()
    if not value:
        return {"error": "Value is required"}, 400
    normalized = normalize_alias(value)
    existing = MappingListItem.query.filter_by(
        domain_id=domain.id,
        list_key=list_key,
        value_normalized=normalized,
    ).first()
    if existing and existing.is_active:
        return {"error": "That value is already stored"}, 409
    if existing:
        before = {"value": existing.value, "is_active": False, "list_key": list_key}
        existing.value = value
        existing.is_active = True
        _audit(domain.code, "restore_list_item", before, {"value": value, "list_key": list_key})
    else:
        row = MappingListItem(
            domain_id=domain.id,
            list_key=list_key,
            value=value,
            value_normalized=normalized,
            is_active=True,
        )
        db.session.add(row)
        db.session.flush()
        _audit(domain.code, "add_list_item", None, {"value": value, "list_key": list_key})
    db.session.commit()
    return _snapshot()


@mapping_config_bp.patch("/list-items/<int:item_id>")
def update_list_item(item_id: int):
    row = db.session.get(MappingListItem, item_id)
    if not row or not row.is_active:
        return {"error": "Value not found"}, 404
    body = request.get_json(silent=True) or {}
    value = str(body.get("value") or "").strip()
    if not value:
        return {"error": "Value is required"}, 400
    normalized = normalize_alias(value)
    clash = MappingListItem.query.filter(
        MappingListItem.domain_id == row.domain_id,
        MappingListItem.list_key == row.list_key,
        MappingListItem.value_normalized == normalized,
        MappingListItem.id != row.id,
    ).first()
    if clash:
        return {"error": "That value is already stored"}, 409
    domain = db.session.get(MappingDomain, row.domain_id)
    before = {"value": row.value, "list_key": row.list_key}
    row.value = value
    row.value_normalized = normalized
    _audit(domain.code if domain else "", "update_list_item", before, {"value": value, "list_key": row.list_key})
    db.session.commit()
    return _snapshot()


@mapping_config_bp.delete("/list-items/<int:item_id>")
def delete_list_item(item_id: int):
    row = db.session.get(MappingListItem, item_id)
    if not row or not row.is_active:
        return {"error": "Value not found"}, 404
    domain = db.session.get(MappingDomain, row.domain_id)
    before = {"value": row.value, "list_key": row.list_key}
    row.is_active = False
    _audit(domain.code if domain else "", "remove_list_item", before, {"is_active": False})
    db.session.commit()
    return _snapshot()


@mapping_config_bp.patch("/settings/<string:setting_key>")
def update_setting(setting_key: str):
    row = db.session.get(MappingSetting, setting_key)
    if not row:
        return {"error": "Setting not found"}, 404
    body = request.get_json(silent=True) or {}
    if "value" not in body:
        return {"error": "Value is required"}, 400
    value = body.get("value")
    if setting_key in {"header_scan_rows", "min_header_matches"}:
        try:
            value = int(value)
        except (TypeError, ValueError):
            return {"error": "Enter a whole number"}, 400
        if value < 0:
            return {"error": "Enter a whole number of 0 or more"}, 400
    elif setting_key == "overrides_by_source":
        if not isinstance(value, dict):
            return {"error": "Overrides must be an object of source names to numbers"}, 400
        cleaned = {}
        for key, raw in value.items():
            try:
                cleaned[str(key)] = int(raw)
            except (TypeError, ValueError):
                return {"error": f"{key} must be a whole number"}, 400
        value = cleaned
    user = get_current_user()
    before = row.value_json
    row.value_json = value
    row.updated_by_user_id = user.id if user else None
    _audit("settings", "update_setting", {"key": setting_key, "value": before}, {"key": setting_key, "value": value})
    db.session.commit()
    return _snapshot()
