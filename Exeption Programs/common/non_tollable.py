"""Vehicle classes that stay in exception output but have no toll rate.

Names live in E15/E15_config.json under non_tollable_vehicle_classes.
Add a name there; do not hardcode class names in the programs.
Aliases from shared_config/vehicle_class.json are included, so listing
3WHEELER also covers auto and three wheeler.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_LIST_PATH = _PROGRAMS / "E15" / "E15_config.json"
_VEHICLE_CLASS_PATH = _PROGRAMS / "common" / "shared_config" / "vehicle_class.json"


def _norm(value) -> str:
    if value is None:
        return ""
    text = str(value).strip().casefold()
    text = re.sub(r"[\s_\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in {"", "nan", "none", "nat"}:
        return ""
    return text


def _alias_groups() -> list[set[str]]:
    if not _VEHICLE_CLASS_PATH.is_file():
        return []
    try:
        payload = json.loads(_VEHICLE_CLASS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    groups: list[set[str]] = []
    for canonical, body in payload.items():
        if str(canonical).startswith("_") or not isinstance(body, dict):
            continue
        group = {_norm(canonical)}
        for alias in body.get("aliases") or []:
            group.add(_norm(alias))
        group.discard("")
        if group:
            groups.append(group)
    return groups


@lru_cache(maxsize=1)
def non_tollable_keys() -> frozenset[str]:
    names: list = []
    if _LIST_PATH.is_file():
        try:
            payload = json.loads(_LIST_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            payload = {}
        raw = payload.get("non_tollable_vehicle_classes") or []
        if isinstance(raw, list):
            names = raw
    listed = {_norm(name) for name in names}
    listed.discard("")
    expanded = set(listed)
    for group in _alias_groups():
        if group & listed:
            expanded |= group
    return frozenset(expanded)


def is_non_tollable_class(value) -> bool:
    key = _norm(value)
    return bool(key) and key in non_tollable_keys()
