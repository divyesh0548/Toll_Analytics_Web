"""Load vehicle class and MOP mapping configs from JSON files.

Alias matching is case-insensitive (values are normalized to uppercase).
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent

# Reserved top-level keys that are not category mappings.
MOP_IGNORE_KEY = "ignore"
VEHICLE_CLASS_EXCLUDE_KEY = "exclude"
RESERVED_MAPPING_KEYS = {MOP_IGNORE_KEY, VEHICLE_CLASS_EXCLUDE_KEY}


def load_mappings(config_file: str) -> dict[str, tuple[str, list[str]]]:
    path = CONFIG_DIR / config_file
    raw = json.loads(path.read_text(encoding="utf-8"))

    mappings: dict[str, tuple[str, list[str]]] = {}
    for canonical, entry in raw.items():
        if canonical in RESERVED_MAPPING_KEYS:
            continue
        if not isinstance(entry, dict):
            raise ValueError(
                f"{config_file}: entry for '{canonical}' must be an object "
                f"with db_column and aliases."
            )
        db_column = entry["db_column"]
        aliases = entry["aliases"]
        if not isinstance(aliases, list):
            raise ValueError(f"{config_file}: aliases for '{canonical}' must be a list.")
        mappings[canonical] = (db_column, aliases)

    return mappings


def load_vehicle_class_mappings() -> dict[str, tuple[str, list[str]]]:
    return load_mappings("vehicle_class.json")


def load_mop_mappings() -> dict[str, tuple[str, list[str]]]:
    return load_mappings("mop.json")


def load_vehicle_class_exclude_aliases() -> list[str]:
    """Raw class labels that are skipped (not counted, do not fail validation)."""
    path = CONFIG_DIR / "vehicle_class.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    excluded = raw.get(VEHICLE_CLASS_EXCLUDE_KEY, [])
    if excluded is None:
        return []
    if not isinstance(excluded, list):
        raise ValueError("vehicle_class.json: 'exclude' must be a list of strings.")
    return [str(item) for item in excluded]


def load_mop_ignore_aliases() -> list[str]:
    """Raw MOP labels that are skipped (not counted, do not fail validation)."""
    path = CONFIG_DIR / "mop.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    ignore = raw.get(MOP_IGNORE_KEY, [])
    if ignore is None:
        return []
    if not isinstance(ignore, list):
        raise ValueError("mop.json: 'ignore' must be a list of strings.")
    return [str(item) for item in ignore]
