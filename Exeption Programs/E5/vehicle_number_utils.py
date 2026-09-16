"""Minimal vehicle-number helpers used by IHMCL_bot.py."""

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
    """Basic Indian VRN shape check (letters + digits, length 6–12)."""
    text = normalize_vehicle_number(value)
    if not text or len(text) < 6 or len(text) > 12:
        return False
    if not re.search(r"[A-Z]", text):
        return False
    if not re.search(r"\d", text):
        return False
    return True
