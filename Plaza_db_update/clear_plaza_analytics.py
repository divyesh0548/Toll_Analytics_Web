"""
Delete plaza analytics fact rows for a date range (local / Docker testing).

Clears all five ETL tables for one plaza_identifier between FROM_DATE and
TO_DATE (inclusive):

  mop_distribution_per_class
  class_distribution_per_lane
  mop_distribution_per_lane
  gap_distribution_per_lane
  revenue_distribution_per_class

Edit the controls below, then:

  python clear_plaza_analytics.py

Uses Website/backend/.env (DB_HOST / DB_NAME or ANALYTICS_DB_NAME / Toll_Analytics_DB).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import psycopg2
from psycopg2 import sql

# ---------------------------------------------------------------------------
# Runtime inputs — edit these, then run the script
# ---------------------------------------------------------------------------

PLAZA_IDENTIFIER = "94ecdec1-550c-4b4c-a94d-1df3b5fb4ac6"

# Inclusive date range (YYYY-MM-DD)
FROM_DATE = "2026-08-01"
TO_DATE = "2026-08-31"

# True = count only, no DELETE
DRY_RUN = False

# True = skip the y/N confirm prompt
SKIP_CONFIRM = False

# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from config.db import get_analytics_db_connection_kwargs  # noqa: E402
from config.settings import (  # noqa: E402
    CLASS_DISTRIBUTION_PER_LANE_TABLE,
    GAP_DISTRIBUTION_PER_LANE_TABLE,
    MOP_DISTRIBUTION_PER_CLASS_TABLE,
    MOP_DISTRIBUTION_PER_LANE_TABLE,
    REVENUE_DISTRIBUTION_PER_CLASS_TABLE,
)

ANALYTICS_TABLES = (
    MOP_DISTRIBUTION_PER_CLASS_TABLE,
    CLASS_DISTRIBUTION_PER_LANE_TABLE,
    MOP_DISTRIBUTION_PER_LANE_TABLE,
    GAP_DISTRIBUTION_PER_LANE_TABLE,
    REVENUE_DISTRIBUTION_PER_CLASS_TABLE,
)


def _parse_date(label: str, value: str) -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise SystemExit(f"Invalid {label}: {value!r} (use YYYY-MM-DD)") from exc


def count_rows(conn, table: str, plaza_identifier: str, start: date, end: date) -> int:
    query = sql.SQL(
        """
        SELECT COUNT(*) FROM {table}
        WHERE plaza_identifier = %s
          AND date >= %s
          AND date <= %s
        """
    ).format(table=sql.Identifier(table))
    with conn.cursor() as cur:
        cur.execute(query, (plaza_identifier, start, end))
        return int(cur.fetchone()[0])


def delete_rows(conn, table: str, plaza_identifier: str, start: date, end: date) -> int:
    query = sql.SQL(
        """
        DELETE FROM {table}
        WHERE plaza_identifier = %s
          AND date >= %s
          AND date <= %s
        """
    ).format(table=sql.Identifier(table))
    with conn.cursor() as cur:
        cur.execute(query, (plaza_identifier, start, end))
        return int(cur.rowcount)


def main() -> int:
    plaza_identifier = str(PLAZA_IDENTIFIER or "").strip()
    if not plaza_identifier or plaza_identifier == "REPLACE_WITH_PLAZA_UUID":
        print("ERROR: set PLAZA_IDENTIFIER at the top of this file.")
        return 1

    start = _parse_date("FROM_DATE", FROM_DATE)
    end = _parse_date("TO_DATE", TO_DATE)
    if end < start:
        print("ERROR: TO_DATE must be on or after FROM_DATE")
        return 1

    kwargs = get_analytics_db_connection_kwargs()
    print(f"Database: {kwargs['database']} @ {kwargs['host']}")
    print(f"Plaza:    {plaza_identifier}")
    print(f"Dates:    {start.isoformat()} → {end.isoformat()} (inclusive)")
    print(f"Mode:     {'DRY RUN' if DRY_RUN else 'DELETE'}")
    print()

    conn = psycopg2.connect(**kwargs)
    try:
        totals: list[tuple[str, int]] = []
        for table in ANALYTICS_TABLES:
            n = count_rows(conn, table, plaza_identifier, start, end)
            totals.append((table, n))
            print(f"  {table}: {n} row(s)")

        grand = sum(n for _, n in totals)
        print(f"\nTotal matching rows: {grand}")
        if grand == 0:
            print("Nothing to delete.")
            return 0

        if DRY_RUN:
            print("Dry run — no changes made. Set DRY_RUN = False to delete.")
            return 0

        if not SKIP_CONFIRM:
            answer = input(
                f"\nDelete {grand} row(s) for this plaza/date range? [y/N] "
            ).strip().lower()
            if answer not in {"y", "yes"}:
                print("Aborted.")
                return 1

        deleted_total = 0
        for table, _before in totals:
            deleted = delete_rows(conn, table, plaza_identifier, start, end)
            deleted_total += deleted
            print(f"  deleted {deleted} from {table}")
        conn.commit()
        print(f"\nDone. Deleted {deleted_total} row(s).")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
