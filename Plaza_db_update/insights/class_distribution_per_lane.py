"""Vehicle class distribution per lane (hourly)."""

from __future__ import annotations

import pandas as pd

from config.settings import (
    CLASS_DISTRIBUTION_PER_LANE_TABLE,
    PLAZA_IDENTIFIER,
    PLAZA_NAME,
)
from insights.db_write import insert_new_rows

DATA_COLUMNS = [
    "plaza_identifier",
    "plaza_name",
    "date",
    "hour",
    "lane",
    "vehicle_class",
    "txn_count",
]
KEY_COLUMNS = ["plaza_identifier", "date", "hour", "lane", "vehicle_class"]


def aggregate(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    usable = df[df["lane_no"].notna() & df["vehicle_class"].notna()].copy()
    if usable.empty:
        return []

    grouped = (
        usable.groupby(["date", "hour", "lane_no", "vehicle_class"], sort=True)
        .size()
        .reset_index(name="txn_count")
    )
    rows: list[dict] = []
    for record in grouped.itertuples(index=False):
        rows.append(
            {
                "plaza_identifier": PLAZA_IDENTIFIER,
                "plaza_name": PLAZA_NAME,
                "date": record.date,
                "hour": record.hour,
                "lane": record.lane_no,
                "vehicle_class": record.vehicle_class,
                "txn_count": int(record.txn_count),
            }
        )
    return rows


def write(conn, rows: list[dict], *, dry_run: bool = False) -> tuple[int, int]:
    if dry_run:
        print(f"  DRY RUN class_distribution_per_lane: {len(rows)} row(s)")
        return len(rows), 0
    return insert_new_rows(
        conn,
        CLASS_DISTRIBUTION_PER_LANE_TABLE,
        DATA_COLUMNS,
        KEY_COLUMNS,
        rows,
        label="class_distribution_per_lane",
    )
