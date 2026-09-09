"""Shared run settings for NHIT dashboard ETL modules."""

from __future__ import annotations

from datetime import date
from pathlib import Path

INSIGHTS_DIR = Path(__file__).resolve().parent.parent

PLAZA_NAME = "aroli"

INPUT_FOLDER = r"C:\Divyesh\NHIT_dashboard_processing\New Dashboard Insights\Input"

# Rows before this date are skipped (noisy / sparse history).
START_DATE_LIMIT = "2025-11-23"
START_DATE_LIMIT_DATE = date.fromisoformat(START_DATE_LIMIT)

# Gap / headway analytics table (module2) — wide columns l01…l12 = avg gap sec.
GAP_DISTRIBUTION_TABLE = "gap_distribution_per_lane"

# Exempt vehicle count per lane (module3) — wide columns l01…l12.
EXEMPT_DISTRIBUTION_TABLE = "exempt_distribution_per_lane"
