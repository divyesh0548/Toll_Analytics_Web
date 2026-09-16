"""MOP distribution per vehicle class (hourly)."""

from __future__ import annotations

import pandas as pd

from config.settings import (
    MOP_DISTRIBUTION_PER_CLASS_TABLE,
    PLAZA_IDENTIFIER,
    PLAZA_NAME,
)
from insights.db_write import upsert_rows

DATA_COLUMNS = [
    "plaza_identifier",
    "plaza_name",
    "date",
    "hour",
    "vehicle_class",
    "mop",
    "txn_count",
]
KEY_COLUMNS = ["plaza_identifier", "date", "hour", "vehicle_class", "mop"]


def aggregate(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    usable = df[df["vehicle_class"].notna() & df["mop"].notna()].copy()
    if usable.empty:
        return []

    grouped = (
        usable.groupby(["date", "hour", "vehicle_class", "mop"], sort=True)
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
                "vehicle_class": record.vehicle_class,
                "mop": record.mop,
                "txn_count": int(record.txn_count),
            }
        )
    return rows


def write(conn, rows: list[dict], *, dry_run: bool = False) -> tuple[int, int]:
    if dry_run:
        print(f"  DRY RUN mop_distribution_per_class: {len(rows)} row(s)")
        return len(rows), 0
    return upsert_rows(
        conn,
        MOP_DISTRIBUTION_PER_CLASS_TABLE,
        DATA_COLUMNS,
        KEY_COLUMNS,
        rows,
        label="mop_distribution_per_class",
    )
