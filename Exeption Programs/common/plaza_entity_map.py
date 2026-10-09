"""
Shared plaza_identifier ↔ submissions.entity_name lookup.

Used by exception programs (E4, E6, …) and the Website job worker so the UI
only needs plazas.plaza_identifier from toll_analytics.
"""

from __future__ import annotations

import json
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parent
MAP_PATH = COMMON_DIR / "plaza_entity_map.json"

_cache: dict[str, str] | None = None


def map_path() -> Path:
    return MAP_PATH


def load_plaza_entity_map(*, force_reload: bool = False) -> dict[str, str]:
    """
    Return {plaza_identifier: entity_name} (non-empty values only).
    """
    global _cache
    if _cache is not None and not force_reload:
        return dict(_cache)

    if not MAP_PATH.is_file():
        raise FileNotFoundError(f"Plaza–entity map not found: {MAP_PATH}")

    raw = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid plaza_entity_map.json root (expected object): {MAP_PATH}")

    section = raw.get("plaza_identifier_to_entity_name")
    if section is None and all(isinstance(k, str) for k in raw.keys()):
        # Allow a flat map without the wrapper key.
        section = {
            k: v
            for k, v in raw.items()
            if not str(k).startswith("_") and isinstance(v, str)
        }
    if not isinstance(section, dict):
        raise ValueError(
            "plaza_entity_map.json must contain "
            "'plaza_identifier_to_entity_name' object."
        )

    cleaned: dict[str, str] = {}
    for plaza_id, entity in section.items():
        pid = str(plaza_id or "").strip()
        name = str(entity or "").strip()
        if not pid or not name:
            continue
        cleaned[pid] = name

    _cache = cleaned
    return dict(cleaned)


def resolve_entity_name(plaza_identifier: str) -> str | None:
    """Look up submissions.entity_name for a plaza_identifier UUID."""
    key = str(plaza_identifier or "").strip()
    if not key:
        return None
    return load_plaza_entity_map().get(key)


def resolve_plaza_identifier(entity_name: str) -> str | None:
    """Reverse lookup: first plaza_identifier that maps to this entity_name."""
    name = str(entity_name or "").strip().casefold()
    if not name:
        return None
    for plaza_id, entity in load_plaza_entity_map().items():
        if str(entity).strip().casefold() == name:
            return plaza_id
    return None


def require_entity_name(plaza_identifier: str) -> str:
    """Like resolve_entity_name but raises with a clear message if missing."""
    entity = resolve_entity_name(plaza_identifier)
    if entity:
        return entity
    raise RuntimeError(
        f"No entity_name mapped for plaza_identifier={plaza_identifier!r}. "
        f"Add it in {MAP_PATH} under plaza_identifier_to_entity_name."
    )
