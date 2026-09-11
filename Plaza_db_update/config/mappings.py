"""Load vehicle class and MOP mapping configs from JSON files."""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent


def load_mappings(config_file: str) -> dict[str, tuple[str, list[str]]]:
    path = CONFIG_DIR / config_file
    raw = json.loads(path.read_text(encoding="utf-8"))

    mappings: dict[str, tuple[str, list[str]]] = {}
    for canonical, entry in raw.items():
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
