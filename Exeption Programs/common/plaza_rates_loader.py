"""Load the single plaza-rate table from Website/backend/app/plaza_rates.py."""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date, datetime
from pathlib import Path

_MODULE = None

# Annexure workbooks match these TC Class labels to rate index 1–6.
_ANNEXURE_TC_INDEX = {
    "car": 1,
    "lcv": 2,
    "trk 2 axle": 3,
    "bus": 3,
    "truck 3 axle": 4,
    "mav": 5,
    "osv": 6,
}


def plaza_rates_path() -> Path:
    override = os.environ.get("WEBSITE_BACKEND_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve() / "app" / "plaza_rates.py"
    # Exeption Programs/common → repo root
    repo = Path(__file__).resolve().parents[2]
    return repo / "Website" / "backend" / "app" / "plaza_rates.py"


def load_plaza_rates_module():
    global _MODULE
    if _MODULE is not None:
        return _MODULE
    path = plaza_rates_path()
    if not path.is_file():
        raise FileNotFoundError(f"Plaza rates module not found: {path}")
    spec = importlib.util.spec_from_file_location("website_plaza_rates", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load plaza rates from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _MODULE = module
    return module


def __getattr__(name: str):
    return getattr(load_plaza_rates_module(), name)


def has_plaza_rates(plaza_name: str) -> bool:
    module = load_plaza_rates_module()
    key = module.normalize_plaza_rate_key(plaza_name)
    if not key:
        return False
    return key in module.PLAZA_RATES or key in module.Plaza_Rates_Apr26_onwards


def _as_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "nat", "none"}:
        return None
    try:
        import pandas as pd

        stamp = pd.to_datetime(text, errors="coerce")
    except Exception:  # noqa: BLE001
        return None
    if stamp is None or getattr(stamp, "__class__", None).__name__ == "NaTType":
        return None
    try:
        if getattr(stamp, "year", None) is None or stamp != stamp:
            return None
    except Exception:  # noqa: BLE001
        return None
    if hasattr(stamp, "date"):
        try:
            return stamp.date()
        except Exception:  # noqa: BLE001
            return None
    return None


def _journey_section(journey_type: str) -> str:
    text = str(journey_type or "").casefold()
    if "local" in text:
        return "local"
    if "return" in text or "cont" in text:
        return "return"
    return "single"


def lookup_annexure_amount(plaza_name: str, tc_class, journey_type, as_of) -> int | None:
    """Rate for one annexure row. Book follows APR26_RATES_START_DATE."""
    module = load_plaza_rates_module()
    book, _source = module.resolve_plaza_rates_dict(plaza_name, as_of_date=_as_date(as_of))
    if not book:
        return None
    index = _ANNEXURE_TC_INDEX.get(str(tc_class or "").strip().casefold())
    if index is None:
        return None
    section = book.get(_journey_section(journey_type)) or {}
    value = section.get(index)
    if value is None:
        return None
    return int(value)
