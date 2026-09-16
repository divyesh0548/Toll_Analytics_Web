"""Shared Excel column mappings, lane aliases, and datetime formats."""

from __future__ import annotations

import re

# Date-only Excel header aliases (no time). When values are date-only, ETL
# looks for a separate TIME column and combines the two.
DATE_COLUMN_ALIASES = [
    "DATE",
    "Date & Time"
]

# Time-only Excel header aliases used with DATE_COLUMN_ALIASES.
TIME_COLUMN_ALIASES = [
    "TIME",
]

# MOP / payment-mode Excel header aliases.
MOP_COLUMN_ALIASES = [
    "MVC MOP",
    "MVC_TLC_MOP",
    "PAYMENT METHOD",
    "Payment Method",
]

# Lane Excel header aliases.
LANE_COLUMN_ALIASES = [
    "LANE",
    "Lane No",
    "Lane No.",
]

# Vehicle-class Excel header aliases.
VEHICLE_CLASS_COLUMN_ALIASES = [
    "MVC",
    "TC Class",
    "MVC_TLC_CLASS",
    "Operator Class",
]

# Excel column name -> logical field
COLUMN_MAPPING = {
    "datetime": DATE_COLUMN_ALIASES[0],
    "vehicle_class": VEHICLE_CLASS_COLUMN_ALIASES[0],
    "lane_no": LANE_COLUMN_ALIASES[0],
    "mop": MOP_COLUMN_ALIASES[0],
}

# Fields required for volume analytics (module1).
VOLUME_REQUIRED_FIELDS = ("datetime", "vehicle_class", "lane_no", "mop")

# Fields required for gap / headway analytics (module2).
GAP_REQUIRED_FIELDS = ("datetime", "lane_no")

# Fields required for exempt-per-lane analytics (module3).
EXEMPT_REQUIRED_FIELDS = ("datetime", "lane_no", "mop")

TOTAL_TRANSACTION_COLUMN = "total_transaction"

# Canonical lane -> (db_column, excel_aliases)
# Standard stored form is always L01…L{MAX_SUPPORTED_LANES}.
# Aliases such as L1 / L2 are accepted and normalized to L01 / L02.
# Any other lane value must stop ETL (no heuristic fallback).
MAX_SUPPORTED_LANES = 12


def _lane_aliases(lane_number: int) -> list[str]:
    padded = f"L{lane_number:02d}"
    short = f"L{lane_number}"
    aliases = [padded, short, f"LANE {lane_number}", f"LANE {lane_number:02d}"]
    # Keep unique while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for alias in aliases:
        key = alias.upper()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(alias)
    return ordered


LANE_MAPPINGS: dict[str, tuple[str, list[str]]] = {
    f"L{i:02d}": (f"l{i:02d}", _lane_aliases(i))
    for i in range(1, MAX_SUPPORTED_LANES + 1)
}

# Gap table: per-lane count of gaps strictly under 2 seconds.
LANE_LT2_COLUMNS: dict[str, str] = {
    f"L{i:02d}": f"l{i:02d}_lt2_count" for i in range(1, MAX_SUPPORTED_LANES + 1)
}

EXCEL_EXTENSIONS = {".xlsx", ".xls", ".csv"}

# Try these formats per file; the one that parses the most values wins.
DATETIME_FORMATS_12H = [
    "%d-%b-%Y %I:%M:%S %p",  # 06-Dec-2025 12:00:52 AM
    "%d-%b-%Y %I:%M %p",     # 06-Dec-2025 2:00 PM
    "%m/%d/%Y %I:%M:%S %p",  # 11/24/2025 2:23:35 AM
    "%m/%d/%Y %I:%M %p",     # 11/24/2025 2:23 AM
    "%d/%m/%Y %I:%M:%S %p",  # 28/05/2026 04:00:25 PM
    "%d/%m/%Y %I:%M %p",
    "%d-%m-%Y %I:%M:%S %p",
    "%d-%m-%Y %I:%M %p",
]

DATETIME_FORMATS_24H = [
    "%d/%m/%Y %H:%M:%S",     # 24/11/2025 14:23:35
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
]

DATETIME_FORMATS = DATETIME_FORMATS_12H + DATETIME_FORMATS_24H

# Date-only formats (used when DATE and TIME are separate columns).
DATE_ONLY_FORMATS = [
    "%d/%m/%Y",   # 28/05/2026
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%d-%b-%Y",   # 28-May-2026
    "%m/%d/%Y",
    "%d/%m/%y",
    "%d-%m-%y",
]

# Time-only formats (used with DATE_ONLY_FORMATS).
TIME_ONLY_FORMATS_12H = [
    "%I:%M:%S %p",  # 04:00:25 PM
    "%I:%M %p",     # 4:00 PM
]

TIME_ONLY_FORMATS_24H = [
    "%H:%M:%S",
    "%H:%M",
]

TIME_ONLY_FORMATS = TIME_ONLY_FORMATS_12H + TIME_ONLY_FORMATS_24H

AM_PM_PATTERN = re.compile(r"\b(AM|PM)\b", re.IGNORECASE)

# Hour bucket stored as TEXT in 24-hour form: "2-3" means 02:00:00-02:59:59.
# Use 24-hour labels (not "2-3 AM") so afternoon hours stay unambiguous ("14-15").

HEADER_KEYWORDS = [
    "Transaction ID",
    "Date & Time",
    "Veh Reg No.",
    "TC Class",
    "Lane No",
    "VEH REG NO",
    "TRANSACTION NO",
    "TC_VEH_REG_NO",
    "PLAZA_NAME",
    "MVC_TLC_CLASS",
    "MVC_TLC_MOP",
    "MVC MOP",
    "MVC",
    "Veh Reg Num",
    "PaymentType",
    "VehicleNumber",
    "Journey Type",
    "Vehicle No",
    "Operator Class",
    "LANE",
]
HEADER_KEYWORDS.extend(DATE_COLUMN_ALIASES)
HEADER_KEYWORDS.extend(TIME_COLUMN_ALIASES)
HEADER_KEYWORDS.extend(MOP_COLUMN_ALIASES)
HEADER_KEYWORDS.extend(LANE_COLUMN_ALIASES)
HEADER_KEYWORDS.extend(VEHICLE_CLASS_COLUMN_ALIASES)
# Include mapped Excel column names in header detection.
HEADER_KEYWORDS.extend(COLUMN_MAPPING.values())


def split_mappings(
    mappings: dict[str, tuple[str, list[str]]],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Split combined config into db-column map and excel-alias map."""
    columns = {canonical: db_column for canonical, (db_column, _aliases) in mappings.items()}
    normalization = {canonical: aliases for canonical, (_db_column, aliases) in mappings.items()}
    return columns, normalization


def normalize_key(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return ""
    text = re.sub(r"\s+", " ", text).upper()
    return text


def build_lookup(normalization: dict[str, list[str]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, aliases in normalization.items():
        lookup[normalize_key(canonical)] = canonical
        for alias in aliases:
            lookup[normalize_key(alias)] = canonical
    return lookup


LANE_COLUMNS, LANE_NORMALIZATION = split_mappings(LANE_MAPPINGS)
LANE_LOOKUP = build_lookup(LANE_NORMALIZATION)


def excel_column_for(field: str) -> str:
    return COLUMN_MAPPING[field]


def required_excel_columns(fields: tuple[str, ...] | list[str]) -> list[str]:
    return [COLUMN_MAPPING[field] for field in fields]
