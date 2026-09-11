"""Gap / headway distribution per lane (hourly)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from config.excel_config import LANE_COLUMNS, LANE_LT2_COLUMNS
from config.settings import (
    GAP_DISTRIBUTION_PER_LANE_TABLE,
    GAP_LT_2S_THRESHOLD,
    PLAZA_IDENTIFIER,
    PLAZA_NAME,
)
from insights.db_write import insert_new_rows

DATA_COLUMNS = [
    "plaza_identifier",
    "plaza_name",
    "date",
    "hour",
    *LANE_COLUMNS.values(),
    *LANE_LT2_COLUMNS.values(),
]
KEY_COLUMNS = ["plaza_identifier", "date", "hour"]


def _average_or_none(values: np.ndarray) -> float | None:
    if values.size == 0:
        return None
    return float(np.mean(values))


def aggregate(df: pd.DataFrame) -> list[dict]:
    """One wide row per plaza + date + hour with per-lane avg gap and <2s counts."""
    usable = df[df["lane_no"].notna() & df["event_dt"].notna()].copy()
    if usable.empty:
        return []

    ordered = usable.sort_values(["lane_no", "event_dt"], kind="mergesort").copy()
    ordered["prev_dt"] = ordered.groupby("lane_no", sort=False)["event_dt"].shift(1)
    ordered["gap_sec"] = (ordered["event_dt"] - ordered["prev_dt"]).dt.total_seconds()
    ordered.loc[ordered["gap_sec"] < 0, "gap_sec"] = np.nan

    hour_keys = ordered.groupby(["date", "hour"], sort=True).size().index
    gap_lookup = {
        key: group.to_numpy(dtype=float, copy=False)
        for key, group in ordered.dropna(subset=["gap_sec"]).groupby(
            ["date", "hour", "lane_no"], sort=True
        )["gap_sec"]
    }

    rows: list[dict] = []
    for record_date, hour_label in hour_keys:
        row: dict = {
            "plaza_identifier": PLAZA_IDENTIFIER,
            "plaza_name": PLAZA_NAME,
            "date": record_date,
            "hour": hour_label,
        }
        for lane, avg_column in LANE_COLUMNS.items():
            gap_values = gap_lookup.get(
                (record_date, hour_label, lane),
                np.array([], dtype=float),
            )
            row[avg_column] = _average_or_none(gap_values)
            lt2_column = LANE_LT2_COLUMNS[lane]
            row[lt2_column] = int(
                sum(1 for value in gap_values if float(value) < GAP_LT_2S_THRESHOLD)
            )
        rows.append(row)
    return rows


def write(conn, rows: list[dict], *, dry_run: bool = False) -> tuple[int, int]:
    if dry_run:
        print(f"  DRY RUN gap_distribution_per_lane: {len(rows)} row(s)")
        return len(rows), 0
    return insert_new_rows(
        conn,
        GAP_DISTRIBUTION_PER_LANE_TABLE,
        DATA_COLUMNS,
        KEY_COLUMNS,
        rows,
        label="gap_distribution_per_lane",
    )
