"""Tell day and month apart when a file uses numeric dates.

A value above 12 cannot be a month. After enough dates are read, the side
that exceeds 12 is the day, and the other side is the month.
"""

from __future__ import annotations

import re

_NUMERIC_DATE = re.compile(
    r"(?<!\d)(\d{1,2})([/\-.])(\d{1,2})\2(\d{2,4})(?!\d)"
)


def infer_day_first(values, *, sample_limit: int = 4000) -> bool | None:
    """
    True  → first number is the day (13/08/2026).
    False → first number is the month (08/13/2026).
    None  → every numeric date is ambiguous (both parts are 1–12).
    """
    day_evidence = 0
    month_evidence = 0
    checked = 0
    for raw in values:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text or text.lower() in {"nan", "none", "nat"}:
            continue
        checked += 1
        if checked > sample_limit and (day_evidence or month_evidence):
            break
        match = _NUMERIC_DATE.search(text)
        if not match:
            continue
        first = int(match.group(1))
        second = int(match.group(3))
        if first > 12 and second <= 12:
            day_evidence += 1
        elif second > 12 and first <= 12:
            month_evidence += 1
    if day_evidence and not month_evidence:
        return True
    if month_evidence and not day_evidence:
        return False
    if day_evidence or month_evidence:
        return day_evidence >= month_evidence
    return None


def series_dayfirst(values, *, default: bool = True) -> bool:
    inferred = infer_day_first(values)
    if inferred is None:
        return default
    return inferred
