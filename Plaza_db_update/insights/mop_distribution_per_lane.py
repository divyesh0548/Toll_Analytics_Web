"""MOP distribution per lane (hourly)."""

from __future__ import annotations

import pandas as pd

from config.settings import (
    MOP_DISTRIBUTION_PER_LANE_TABLE,
    PLAZA_IDENTIFIER,
    PLAZA_NAME,
)
from insights.db_write import upsert_rows

DATA_COLUMNS = [
    "plaza_identifier",
    "plaza_name",
    "date",
    "hour",
    "lane",
    "mop",
    "txn_count",
]
KEY_COLUMNS = ["plaza_identifier", "date", "hour", "lane", "mop"]


def aggregate(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    usable = df[df["lane_no"].notna() & df["mop"].notna()].copy()
    if usable.empty:
        return []

    grouped = (
        usable.groupby(["date", "hour", "lane_no", "mop"], sort=True)
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
                "mop": record.mop,
                "txn_count": int(record.txn_count),
            }
        )
    return rows


def write(conn, rows: list[dict], *, dry_run: bool = False) -> tuple[int, int]:
    if dry_run:
        print(f"  DRY RUN mop_distribution_per_lane: {len(rows)} row(s)")
        return len(rows), 0
    return upsert_rows(
        conn,
        MOP_DISTRIBUTION_PER_LANE_TABLE,
        DATA_COLUMNS,
        KEY_COLUMNS,
        rows,
        label="mop_distribution_per_lane",
    )
