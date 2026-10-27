"""Load vehicle class and MOP mappings from the shared mapping tables.

Vehicle class aliases are compared after uppercasing and removing spaces and symbols.
MOP aliases are compared case-insensitively, with spacing collapsed.
"""

from __future__ import annotations

import sys
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent
_PROGRAMS = CONFIG_DIR.parents[1] / "Exeption Programs"
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

from common.mapping_store import (  # noqa: E402
    list_values,
    mop_mappings,
    vehicle_class_mappings,
)

# Reserved top-level keys that are not category mappings.
MOP_IGNORE_KEY = "ignore"
VEHICLE_CLASS_EXCLUDE_KEY = "exclude"
RESERVED_MAPPING_KEYS = {MOP_IGNORE_KEY, VEHICLE_CLASS_EXCLUDE_KEY}


def load_vehicle_class_mappings() -> dict[str, tuple[str, list[str]]]:
    return vehicle_class_mappings()


def load_mop_mappings() -> dict[str, tuple[str, list[str]]]:
    return mop_mappings()


def load_vehicle_class_exclude_aliases() -> list[str]:
    """Raw class labels that are skipped (not counted, do not fail validation)."""
    return list_values("vehicle_class", VEHICLE_CLASS_EXCLUDE_KEY)


def load_mop_ignore_aliases() -> list[str]:
    """Raw MOP labels that are skipped (not counted, do not fail validation)."""
    return list_values("mop", MOP_IGNORE_KEY)
