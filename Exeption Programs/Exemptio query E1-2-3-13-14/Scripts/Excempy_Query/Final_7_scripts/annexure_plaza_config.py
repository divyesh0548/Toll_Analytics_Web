"""
Plaza → annexure input file mapping for the post–Final Exempt step.

Approved Exemption script runs only when the plaza is listed under
approved_exemption_files. All other plazas use Classwise Annexure.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

CONFIG_DIR = Path(__file__).resolve().parent
CONFIG_PATH = CONFIG_DIR / "annexure_plaza_config.json"
APPROVED_EXEMPTION_DIR = CONFIG_DIR.parent / "Approved Exmption"
RATES_DIR = CONFIG_DIR.parent / "RatesAfter April"

APPROVED_EXEMPTION_SCRIPT = "Aprooved Exemption (1).py"
CLASSWISE_ANNEXURE_SCRIPT = "Classwise Annexure Single rate file.py"


def _load_raw() -> dict:
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def get_approved_exemption_map() -> Dict[str, str]:
    raw = _load_raw().get("approved_exemption_files") or {}
    return {
        str(plaza).strip().upper(): str(filename).strip()
        for plaza, filename in raw.items()
        if str(plaza).strip() and str(filename).strip()
    }


def get_rates_map() -> Dict[str, str]:
    raw = _load_raw().get("rates_files") or {}
    return {
        str(plaza).strip().upper(): str(filename).strip()
        for plaza, filename in raw.items()
        if str(plaza).strip() and str(filename).strip()
    }


def get_plaza_identifier_map() -> Dict[str, str]:
    """Plaza dropdown name → audit_exception_metrics.plaza_identifier."""
    raw = _load_raw().get("plaza_identifiers") or {}
    return {
        str(plaza).strip().upper(): str(identifier).strip()
        for plaza, identifier in raw.items()
        if str(plaza).strip() and str(identifier).strip()
    }


def resolve_plaza_identifier(plaza_name: str) -> Optional[str]:
    key = str(plaza_name or "").strip().upper()
    if not key:
        return None
    return get_plaza_identifier_map().get(key) or None


def uses_approved_exemption_script(plaza_name: str) -> bool:
    key = str(plaza_name or "").strip().upper()
    return key in get_approved_exemption_map()


def resolve_approved_exemption_file(
    plaza_name: str,
    upload_override: Optional[Path] = None,
) -> Optional[Path]:
    """Prefer user upload; otherwise use the plaza default under Approved Exmption/."""
    if upload_override is not None and Path(upload_override).is_file():
        return Path(upload_override).resolve()
    key = str(plaza_name or "").strip().upper()
    filename = get_approved_exemption_map().get(key)
    if not filename:
        return None
    candidate = APPROVED_EXEMPTION_DIR / filename
    return candidate.resolve() if candidate.is_file() else None


def resolve_rates_file(
    plaza_name: str,
    upload_override: Optional[Path] = None,
) -> Optional[Path]:
    """Prefer user upload; otherwise use the plaza default under RatesAfter April/."""
    if upload_override is not None and Path(upload_override).is_file():
        return Path(upload_override).resolve()
    key = str(plaza_name or "").strip().upper()
    filename = get_rates_map().get(key)
    if not filename:
        return None
    candidate = RATES_DIR / filename
    return candidate.resolve() if candidate.is_file() else None


def annexure_script_name_for_plaza(plaza_name: str) -> str:
    if uses_approved_exemption_script(plaza_name):
        return APPROVED_EXEMPTION_SCRIPT
    return CLASSWISE_ANNEXURE_SCRIPT
