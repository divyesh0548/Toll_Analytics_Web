"""Canonical lane labels: L1 and L01 are the same lane, written as L01."""

from __future__ import annotations

import math
import re


def canonicalize_lane_label(lane) -> str:
    """
    Map lane values to L01, L02, ... L10, L11.

    L1, L01, and L001 are L01. L11 and L12 stay L11 and L12.
    """
    if lane is None:
        return ""
    if isinstance(lane, float):
        if math.isnan(lane):
            return ""
        if lane.is_integer():
            lane = int(lane)

    text = str(lane).strip()
    if not text or text.casefold() in {"nan", "none", "<na>"}:
        return ""
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]

    text = text.upper().split("-", 1)[0].strip()
    text = re.sub(r"^LANE\s+", "L", text)
    text = re.sub(r"^LN0*", "L", text)

    match = re.fullmatch(r"L0*(\d+)", text) or re.fullmatch(r"(\d+)", text)
    if not match:
        return text
    return f"L{int(match.group(1)):02d}"
