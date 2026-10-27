"""Load Exeption Programs/common/shared_config JSON into mapping_* tables.

Not called on startup. Run explicitly:

    flask --app run:app seed-shared-config
    flask --app run:app seed-shared-config --replace
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.extensions import db
from app.models.mapping_config import (
    MappingAlias,
    MappingCanonical,
    MappingDomain,
    MappingListItem,
    MappingSetting,
)
from app.services.repo_paths import exception_programs_root

DOMAINS: list[tuple[str, str, int]] = [
    ("vehicle_class", "Vehicle class", 10),
    ("mop", "Mode of payment", 20),
    ("column_alias", "Column aliases", 30),
    ("header_keyword", "Header keywords", 40),
    ("tc_index", "TC class index", 50),
    ("journey_type", "Journey type", 60),
    ("pass_type", "Pass type values", 70),
]

# filename, domain code, list keys that are not canonical buckets
_LIST_FILES: list[tuple[str, str, frozenset[str]]] = [
    ("vehicle_class.json", "vehicle_class", frozenset({"exclude"})),
    ("mop.json", "mop", frozenset({"ignore"})),
]

_ALIAS_FILES: list[tuple[str, str]] = [
    ("column_aliases.json", "column_alias"),
    ("header_keywords.json", "header_keyword"),
    ("tc_class_index_map.json", "tc_index"),
    ("journey_type_map.json", "journey_type"),
    ("pass_type_values.json", "pass_type"),
]


def normalize_alias(value: str) -> str:
    """Casefold and collapse separators so BUS and bus cannot both be stored."""
    text = str(value or "").casefold().strip().replace("\\", "/")
    text = re.sub(r"[\s\-_/]+", " ", text)
    return " ".join(text.split())


def shared_config_dir() -> Path:
    return exception_programs_root() / "common" / "shared_config"


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected object in {path}")
    return data


def _ensure_domains() -> dict[str, MappingDomain]:
    by_code: dict[str, MappingDomain] = {}
    for code, label, order in DOMAINS:
        row = MappingDomain.query.filter_by(code=code).first()
        if row is None:
            row = MappingDomain(code=code, label=label, sort_order=order)
            db.session.add(row)
            db.session.flush()
        else:
            row.label = label
            row.sort_order = order
        by_code[code] = row
    return by_code


def _add_alias(
    *,
    domain: MappingDomain,
    canonical: MappingCanonical,
    alias: str,
    seen: set[str],
    skipped: list[str],
) -> None:
    raw = str(alias or "").strip()
    if not raw:
        return
    norm = normalize_alias(raw)
    if not norm or norm in seen:
        if norm in seen:
            skipped.append(f"{domain.code}: duplicate alias {raw!r}")
        return
    seen.add(norm)
    db.session.add(
        MappingAlias(
            domain_id=domain.id,
            canonical_id=canonical.id,
            alias=raw,
            alias_normalized=norm,
            is_active=True,
        )
    )


def _seed_bucket_file(
    path: Path,
    domain: MappingDomain,
    *,
    list_keys: frozenset[str],
    seen: set[str],
    skipped: list[str],
    counts: dict[str, int],
) -> None:
    data = _load_json(path)
    sort_order = 0
    for key, value in data.items():
        if str(key).startswith("_"):
            continue
        if key in list_keys:
            if not isinstance(value, list):
                raise RuntimeError(f"{path.name}: {key} must be a list")
            list_seen: set[str] = set()
            for item in value:
                raw = str(item or "").strip()
                norm = normalize_alias(raw)
                if not raw or not norm or norm in list_seen:
                    continue
                list_seen.add(norm)
                db.session.add(
                    MappingListItem(
                        domain_id=domain.id,
                        list_key=str(key),
                        value=raw,
                        value_normalized=norm,
                        is_active=True,
                    )
                )
                counts["list_items"] += 1
            continue
        if not isinstance(value, dict):
            raise RuntimeError(f"{path.name}: {key} must be an object with aliases")
        sort_order += 1
        canonical = MappingCanonical(
            domain_id=domain.id,
            canonical_key=str(key),
            db_column=(str(value.get("db_column")).strip() or None)
            if value.get("db_column")
            else None,
            sort_order=sort_order,
            is_active=True,
            notes=(str(value.get("_note")).strip() or None) if value.get("_note") else None,
        )
        db.session.add(canonical)
        db.session.flush()
        counts["canonicals"] += 1
        aliases = value.get("aliases") or []
        if not isinstance(aliases, list):
            raise RuntimeError(f"{path.name}: {key}.aliases must be a list")
        for alias in aliases:
            before = len(seen)
            _add_alias(
                domain=domain,
                canonical=canonical,
                alias=str(alias),
                seen=seen,
                skipped=skipped,
            )
            if len(seen) > before:
                counts["aliases"] += 1


def _seed_alias_list_file(
    path: Path,
    domain: MappingDomain,
    *,
    seen: set[str],
    skipped: list[str],
    counts: dict[str, int],
) -> None:
    data = _load_json(path)
    sort_order = 0
    for key, value in data.items():
        if str(key).startswith("_"):
            continue
        if not isinstance(value, list):
            raise RuntimeError(f"{path.name}: {key} must be a list of aliases")
        sort_order += 1
        canonical = MappingCanonical(
            domain_id=domain.id,
            canonical_key=str(key),
            db_column=None,
            sort_order=sort_order,
            is_active=True,
        )
        db.session.add(canonical)
        db.session.flush()
        counts["canonicals"] += 1
        for alias in value:
            before = len(seen)
            _add_alias(
                domain=domain,
                canonical=canonical,
                alias=str(alias),
                seen=seen,
                skipped=skipped,
            )
            if len(seen) > before:
                counts["aliases"] += 1


def _seed_settings(path: Path, counts: dict[str, int]) -> None:
    data = _load_json(path)
    now = datetime.now(timezone.utc)
    for key, value in data.items():
        if str(key).startswith("_"):
            continue
        db.session.add(
            MappingSetting(key=str(key), value_json=value, updated_at=now)
        )
        counts["settings"] += 1


def _has_seed_data() -> bool:
    return (
        MappingCanonical.query.count() > 0
        or MappingListItem.query.count() > 0
        or MappingSetting.query.count() > 0
    )


def _clear_seed_data() -> None:
    MappingAlias.query.delete()
    MappingListItem.query.delete()
    MappingCanonical.query.delete()
    MappingSetting.query.delete()
    MappingDomain.query.delete()
    db.session.commit()


def seed_shared_config(*, replace: bool = False) -> dict:
    """
    Insert shared_config JSON into mapping_* tables.

    Refuses when rows already exist unless replace=True (wipe then reseed).
    """
    root = shared_config_dir()
    if not root.is_dir():
        raise FileNotFoundError(f"Shared config folder not found: {root}")

    if _has_seed_data():
        if not replace:
            raise RuntimeError(
                "Mapping tables already contain data. "
                "Re-run with --replace to wipe and reseed."
            )
        _clear_seed_data()

    domains = _ensure_domains()
    counts = {"canonicals": 0, "aliases": 0, "list_items": 0, "settings": 0}
    skipped: list[str] = []

    for filename, code, list_keys in _LIST_FILES:
        seen: set[str] = set()
        _seed_bucket_file(
            root / filename,
            domains[code],
            list_keys=list_keys,
            seen=seen,
            skipped=skipped,
            counts=counts,
        )

    for filename, code in _ALIAS_FILES:
        seen = set()
        _seed_alias_list_file(
            root / filename,
            domains[code],
            seen=seen,
            skipped=skipped,
            counts=counts,
        )

    _seed_settings(root / "detection_defaults.json", counts)
    db.session.commit()
    return {"root": str(root), "counts": counts, "skipped": skipped}
