"""Shared prepare / validate helpers for plaza ETL insights."""

from __future__ import annotations

import pandas as pd

from config.excel_config import COLUMN_MAPPING, VOLUME_REQUIRED_FIELDS
from config.settings import PLAZA_IDENTIFIER, PLAZA_NAME, START_DATE_LIMIT_DATE
from excel_common import (
    find_column,
    hour_bucket_label,
    is_blank,
    lane_limit_error_message,
    optional_normalize_lane,
    optional_normalize_mop,
    optional_normalize_vehicle_class,
    safe_parse_datetime,
    try_normalize_lane,
    try_normalize_mop,
    try_normalize_vehicle_class,
    try_parse_datetime,
    unsupported_high_lane_counts,
)

REQUIRED_FIELDS = VOLUME_REQUIRED_FIELDS


def require_plaza_settings() -> None:
    if not PLAZA_IDENTIFIER or PLAZA_IDENTIFIER == "REPLACE_WITH_PLAZA_UUID":
        raise RuntimeError(
            "Set PLAZA_IDENTIFIER in Plaza_db_update/config/settings.py "
            "to the plaza UUID from the website."
        )
    if not PLAZA_NAME or not str(PLAZA_NAME).strip():
        raise RuntimeError("Set PLAZA_NAME in Plaza_db_update/config/settings.py.")


def validate_dataframe(df: pd.DataFrame, file_name: str, datetime_format: str) -> list[str]:
    datetime_col = find_column(df, COLUMN_MAPPING["datetime"])
    vehicle_col = find_column(df, COLUMN_MAPPING["vehicle_class"])
    lane_col = find_column(df, COLUMN_MAPPING["lane_no"])
    mop_col = find_column(df, COLUMN_MAPPING["mop"])

    invalid_datetimes: dict[str, int] = {}
    unmapped_vehicle_classes: dict[str, int] = {}
    unmapped_lanes: dict[str, int] = {}
    unmapped_mops: dict[str, int] = {}
    raw_lanes: list = []

    for _row_idx, row in df.iterrows():
        datetime_value = row[datetime_col]
        if not is_blank(datetime_value):
            if try_parse_datetime(datetime_value, datetime_format=datetime_format) is None:
                raw_dt = str(datetime_value).strip()
                invalid_datetimes[raw_dt] = invalid_datetimes.get(raw_dt, 0) + 1

        vehicle_value = row[vehicle_col]
        if not is_blank(vehicle_value):
            if try_normalize_vehicle_class(vehicle_value) is None:
                raw_vc = str(vehicle_value).strip()
                unmapped_vehicle_classes[raw_vc] = unmapped_vehicle_classes.get(raw_vc, 0) + 1

        lane_value = row[lane_col]
        if not is_blank(lane_value):
            raw_lanes.append(lane_value)
            if try_normalize_lane(lane_value) is None:
                raw_lane = str(lane_value).strip()
                unmapped_lanes[raw_lane] = unmapped_lanes.get(raw_lane, 0) + 1

        mop_value = row[mop_col]
        if not is_blank(mop_value):
            if try_normalize_mop(mop_value) is None:
                raw_mop = str(mop_value).strip()
                unmapped_mops[raw_mop] = unmapped_mops.get(raw_mop, 0) + 1

    errors: list[str] = []
    if invalid_datetimes:
        errors.append(
            f"Invalid datetime values in '{file_name}' ({datetime_col}): "
            + ", ".join(
                f"{value!r} ({count} row(s))"
                for value, count in sorted(invalid_datetimes.items())
            )
        )
    if unmapped_vehicle_classes:
        errors.append(
            f"Unmapped vehicle class values in '{file_name}' ({vehicle_col}): "
            + ", ".join(
                f"{value!r} ({count} row(s))"
                for value, count in sorted(unmapped_vehicle_classes.items())
            )
        )
    high_lanes = unsupported_high_lane_counts(raw_lanes)
    if high_lanes:
        errors.append(lane_limit_error_message(file_name, lane_col, high_lanes))
    if unmapped_lanes:
        remaining = {
            value: count
            for value, count in unmapped_lanes.items()
            if value not in high_lanes
        }
        if remaining:
            errors.append(
                f"Unmapped lane values in '{file_name}' ({lane_col}): "
                + ", ".join(
                    f"{value!r} ({count} row(s))"
                    for value, count in sorted(remaining.items())
                )
            )
    if unmapped_mops:
        errors.append(
            f"Unmapped MOP values in '{file_name}' ({mop_col}): "
            + ", ".join(
                f"{value!r} ({count} row(s))"
                for value, count in sorted(unmapped_mops.items())
            )
        )
    return errors


def print_validation_errors(errors: list[str]) -> None:
    print("\n" + "=" * 80)
    print("VALIDATION FAILED — abnormal data found. DB insertion skipped.")
    print("=" * 80)
    for error in errors:
        print(f"  - {error}")
    print("=" * 80)


def prepare_dataframe(df: pd.DataFrame, datetime_format: str) -> pd.DataFrame:
    """Normalize one VRN file into shared columns for all insight modules."""
    datetime_col = find_column(df, COLUMN_MAPPING["datetime"])
    vehicle_col = find_column(df, COLUMN_MAPPING["vehicle_class"])
    lane_col = find_column(df, COLUMN_MAPPING["lane_no"])
    mop_col = find_column(df, COLUMN_MAPPING["mop"])

    prepared = pd.DataFrame()
    prepared["event_dt"] = df[datetime_col].map(
        lambda value: safe_parse_datetime(value, datetime_format)
    )
    prepared["vehicle_class"] = df[vehicle_col].map(optional_normalize_vehicle_class)
    prepared["lane_no"] = df[lane_col].map(optional_normalize_lane)
    prepared["mop"] = df[mop_col].map(optional_normalize_mop)

    prepared = prepared[prepared["event_dt"].notna()].copy()
    prepared["hour"] = prepared["event_dt"].map(hour_bucket_label)
    prepared["date"] = prepared["event_dt"].dt.date
    prepared = prepared[prepared["date"] >= START_DATE_LIMIT_DATE].copy()
    return prepared
