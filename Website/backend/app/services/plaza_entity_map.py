"""Load Exeption Programs/common/plaza_entity_map.json for Website jobs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

def _common_dir() -> Path:
    from app.services.repo_paths import exception_programs_root

    return exception_programs_root() / "common"


def plaza_entity_map_path() -> Path:
    return _common_dir() / "plaza_entity_map.json"


def load_plaza_entity_map() -> dict[str, str]:
    common_dir = _common_dir()
    map_path = common_dir / "plaza_entity_map.json"
    if str(common_dir) not in sys.path:
        sys.path.insert(0, str(common_dir.parent))
    try:
        from common.plaza_entity_map import load_plaza_entity_map as _load

        return _load()
    except Exception:
        # Fallback: read JSON directly if common import fails.
        if not map_path.is_file():
            return {}
        raw = json.loads(map_path.read_text(encoding="utf-8"))
        section = raw.get("plaza_identifier_to_entity_name") or {}
        return {
            str(k).strip(): str(v).strip()
            for k, v in section.items()
            if str(k).strip() and str(v).strip()
        }


def resolve_entity_name(plaza_identifier: str) -> str | None:
    key = str(plaza_identifier or "").strip()
    if not key:
        return None
    return load_plaza_entity_map().get(key)


def require_entity_name(plaza_identifier: str) -> str:
    entity = resolve_entity_name(plaza_identifier)
    if entity:
        return entity
    raise RuntimeError(
        f"No entity_name mapped for plaza_identifier={plaza_identifier!r}. "
        f"Add it in {_MAP_PATH}."
    )
