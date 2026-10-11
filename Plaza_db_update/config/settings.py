"""Shared run settings for Plaza_db_update ETL."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

PLAZA_UPDATE_DIR = Path(__file__).resolve().parent.parent

# Must match plazas.plaza_identifier created on the website.
PLAZA_IDENTIFIER = "39d45059-341d-435b-8824-9963b4e2068e"

# Display name stored alongside plaza_identifier.
PLAZA_NAME = "aroli"

INPUT_FOLDER = r"C:\Divyesh\Toll Analytics Dashboard\Odhaki Paipkhar VRNs\odhaki_paipkhar"
# Optional local ETC folder (Website jobs). When set, module4 skips submissions download.
ETC_INPUT_FOLDER = ""

# Rows before this date are skipped (noisy / sparse history).
START_DATE_LIMIT = "2025-11-23"
START_DATE_LIMIT_DATE = date.fromisoformat(START_DATE_LIMIT)


def apply_website_env_overrides() -> None:
    """Apply PLAZA_ETL_* env from Website analytics job runner."""
    global PLAZA_IDENTIFIER, PLAZA_NAME, INPUT_FOLDER, ETC_INPUT_FOLDER
    global START_DATE_LIMIT, START_DATE_LIMIT_DATE

    if os.environ.get("PLAZA_ETL_PLAZA_IDENTIFIER", "").strip():
        PLAZA_IDENTIFIER = os.environ["PLAZA_ETL_PLAZA_IDENTIFIER"].strip()
    if os.environ.get("PLAZA_ETL_PLAZA_NAME", "").strip():
        PLAZA_NAME = os.environ["PLAZA_ETL_PLAZA_NAME"].strip()
    if os.environ.get("PLAZA_ETL_VRN_FOLDER", "").strip():
        INPUT_FOLDER = os.environ["PLAZA_ETL_VRN_FOLDER"].strip()
    if "PLAZA_ETL_ETC_FOLDER" in os.environ:
        ETC_INPUT_FOLDER = os.environ.get("PLAZA_ETL_ETC_FOLDER", "").strip()
    if os.environ.get("PLAZA_ETL_START_DATE_LIMIT", "").strip():
        START_DATE_LIMIT = os.environ["PLAZA_ETL_START_DATE_LIMIT"].strip()
        START_DATE_LIMIT_DATE = date.fromisoformat(START_DATE_LIMIT)

# Analytics fact tables (names describe the grain).
MOP_DISTRIBUTION_PER_CLASS_TABLE = "mop_distribution_per_class"
CLASS_DISTRIBUTION_PER_LANE_TABLE = "class_distribution_per_lane"
MOP_DISTRIBUTION_PER_LANE_TABLE = "mop_distribution_per_lane"
GAP_DISTRIBUTION_PER_LANE_TABLE = "gap_distribution_per_lane"
REVENUE_DISTRIBUTION_PER_CLASS_TABLE = "revenue_distribution_per_class"

# Gaps strictly below this threshold (seconds) count as potential tailgating.
GAP_LT_2S_THRESHOLD = 2.0
