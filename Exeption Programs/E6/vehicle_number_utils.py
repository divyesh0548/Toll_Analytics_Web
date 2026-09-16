"""Minimal vehicle-number helpers for E6 permit scrape."""

from __future__ import annotations

import re


def normalize_vehicle_number(value) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    if text.lower() in {"nan", "none", ""}:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text)


def is_vehicle_number_eligible(value) -> bool:
    """Parivahan checkpost form accepts 8–10 char cleaned VRNs."""
    text = normalize_vehicle_number(value)
    if not text or len(text) not in {8, 9, 10}:
        return False
    if not re.search(r"[A-Z]", text):
        return False
    if not re.search(r"\d", text):
        return False
    return True
