"""Shared comparison key for column names and header keywords.

Strip, casefold, then keep only letters and digits. Spaces and symbols
are removed, so "TC Class", "tc_class", "TC-Class", and "TcClass" compare equal.
"""

from __future__ import annotations


def normalize_header_match(value) -> str:
    if value is None:
        return ""
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip().casefold()
    if text in {"nan", "none", "nat", "<na>"}:
        return ""
    return "".join(ch for ch in text if ch.isalnum())
