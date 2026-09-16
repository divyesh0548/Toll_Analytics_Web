"""Shared run settings for Plaza_db_update ETL."""

from __future__ import annotations

from datetime import date
from pathlib import Path

PLAZA_UPDATE_DIR = Path(__file__).resolve().parent.parent

# Must match plazas.plaza_identifier created on the website.
PLAZA_IDENTIFIER = "d55c2122-117c-45be-8554-7ea76730932b"

# Display name stored alongside plaza_identifier.
PLAZA_NAME = "odhaki_paipkhar"

INPUT_FOLDER = r"C:\Divyesh\Toll Analytics Dashboard\Odhaki Paipkhar VRNs\odhaki_paipkhar"

# Rows before this date are skipped (noisy / sparse history).
START_DATE_LIMIT = "2025-11-23"
START_DATE_LIMIT_DATE = date.fromisoformat(START_DATE_LIMIT)

# Analytics fact tables (names describe the grain).
MOP_DISTRIBUTION_PER_CLASS_TABLE = "mop_distribution_per_class"
CLASS_DISTRIBUTION_PER_LANE_TABLE = "class_distribution_per_lane"
MOP_DISTRIBUTION_PER_LANE_TABLE = "mop_distribution_per_lane"
GAP_DISTRIBUTION_PER_LANE_TABLE = "gap_distribution_per_lane"

# Gaps strictly below this threshold (seconds) count as potential tailgating.
GAP_LT_2S_THRESHOLD = 2.0
