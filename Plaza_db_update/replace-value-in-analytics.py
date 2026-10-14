"""
Replace vehicle_class values in revenue_distribution_per_class.

Unique key: (plaza_identifier, date, hour, vehicle_class).
When the target class already exists for the same date/hour, revenue and
txn_count are summed into that row and the old row is deleted.

Edit the controls below, then:

  python replace-value-in-analytics.py

Uses Website/backend/.env (same as other Plaza_db_update scripts).
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

# ---------------------------------------------------------------------------
# Runtime inputs — edit these, then run the script
# ---------------------------------------------------------------------------

PLAZA_IDENTIFIER = "d55c2122-117c-45be-8554-7ea76730932b"

# Exact vehicle_class values as stored in the table (canonical labels).
FROM_VEHICLE_CLASS = "TRUCK 7 AXLE"
TO_VEHICLE_CLASS = "OSV"

# True = preview counts only, no UPDATE/DELETE
DRY_RUN = False

# True = skip the y/N confirm prompt
SKIP_CONFIRM = False

# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from config.db import get_analytics_db_connection_kwargs  # noqa: E402
from config.settings import REVENUE_DISTRIBUTION_PER_CLASS_TABLE  # noqa: E402


def _require_inputs() -> tuple[str, str, str]:
    plaza = str(PLAZA_IDENTIFIER or "").strip()
    from_class = str(FROM_VEHICLE_CLASS or "").strip()
    to_class = str(TO_VEHICLE_CLASS or "").strip()
    if not plaza:
        raise SystemExit("Set PLAZA_IDENTIFIER.")
    if not from_class:
        raise SystemExit("Set FROM_VEHICLE_CLASS.")
    if not to_class:
        raise SystemExit("Set TO_VEHICLE_CLASS.")
    if from_class == to_class:
        raise SystemExit("FROM_VEHICLE_CLASS and TO_VEHICLE_CLASS must differ.")
    return plaza, from_class, to_class


def fetch_plaza_name(conn, plaza_identifier: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT plaza_name
            FROM plazas
            WHERE plaza_identifier = %s
            """,
            (plaza_identifier,),
        )
        row = cur.fetchone()
        return str(row[0]) if row else None


def count_from_class(conn, plaza: str, from_class: str) -> int:
    query = sql.SQL(
        """
        SELECT COUNT(*)
        FROM {table}
        WHERE plaza_identifier = %s
          AND vehicle_class = %s
        """
    ).format(table=sql.Identifier(REVENUE_DISTRIBUTION_PER_CLASS_TABLE))
    with conn.cursor() as cur:
        cur.execute(query, (plaza, from_class))
        return int(cur.fetchone()[0])


def count_conflicts(conn, plaza: str, from_class: str, to_class: str) -> int:
    """Rows where both FROM and TO already exist for the same date+hour."""
    query = sql.SQL(
        """
        SELECT COUNT(*)
        FROM {table} src
        WHERE src.plaza_identifier = %s
          AND src.vehicle_class = %s
          AND EXISTS (
            SELECT 1
            FROM {table} dst
            WHERE dst.plaza_identifier = src.plaza_identifier
              AND dst.date = src.date
              AND dst.hour = src.hour
              AND dst.vehicle_class = %s
          )
        """
    ).format(table=sql.Identifier(REVENUE_DISTRIBUTION_PER_CLASS_TABLE))
    with conn.cursor() as cur:
        cur.execute(query, (plaza, from_class, to_class))
        return int(cur.fetchone()[0])


def sample_rows(conn, plaza: str, from_class: str, limit: int = 8) -> list[tuple]:
    query = sql.SQL(
        """
        SELECT date, hour, revenue, txn_count
        FROM {table}
        WHERE plaza_identifier = %s
          AND vehicle_class = %s
        ORDER BY date, hour
        LIMIT %s
        """
    ).format(table=sql.Identifier(REVENUE_DISTRIBUTION_PER_CLASS_TABLE))
    with conn.cursor() as cur:
        cur.execute(query, (plaza, from_class, limit))
        return list(cur.fetchall())


def merge_conflicts(conn, plaza: str, from_class: str, to_class: str) -> int:
    """
    Add FROM revenue/txn into existing TO rows for the same date/hour,
    then delete those FROM rows. Returns number of FROM rows merged away.
    """
    table = sql.Identifier(REVENUE_DISTRIBUTION_PER_CLASS_TABLE)
    update_sql = sql.SQL(
        """
        UPDATE {table} AS dst
        SET revenue = dst.revenue + src.revenue,
            txn_count = dst.txn_count + src.txn_count
        FROM {table} AS src
        WHERE src.plaza_identifier = %s
          AND src.vehicle_class = %s
          AND dst.plaza_identifier = src.plaza_identifier
          AND dst.date = src.date
          AND dst.hour = src.hour
          AND dst.vehicle_class = %s
        """
    ).format(table=table)
    delete_sql = sql.SQL(
        """
        DELETE FROM {table} AS src
        WHERE src.plaza_identifier = %s
          AND src.vehicle_class = %s
          AND EXISTS (
            SELECT 1
            FROM {table} AS dst
            WHERE dst.plaza_identifier = src.plaza_identifier
              AND dst.date = src.date
              AND dst.hour = src.hour
              AND dst.vehicle_class = %s
          )
        """
    ).format(table=table)
    with conn.cursor() as cur:
        cur.execute(update_sql, (plaza, from_class, to_class))
        cur.execute(delete_sql, (plaza, from_class, to_class))
        return int(cur.rowcount)


def rename_remaining(conn, plaza: str, from_class: str, to_class: str) -> int:
    """Simple rename when no TO row exists for that date/hour."""
    query = sql.SQL(
        """
        UPDATE {table}
        SET vehicle_class = %s
        WHERE plaza_identifier = %s
          AND vehicle_class = %s
        """
    ).format(table=sql.Identifier(REVENUE_DISTRIBUTION_PER_CLASS_TABLE))
    with conn.cursor() as cur:
        cur.execute(query, (to_class, plaza, from_class))
        return int(cur.rowcount)


def main() -> int:
    plaza, from_class, to_class = _require_inputs()
    kwargs = get_analytics_db_connection_kwargs()

    print("=" * 60)
    print("Replace vehicle_class on revenue_distribution_per_class")
    print(f"DB: {kwargs['database']}")
    print(f"Table: {REVENUE_DISTRIBUTION_PER_CLASS_TABLE}")
    print(f"Plaza: {plaza}")
    print(f"From: {from_class!r}  →  To: {to_class!r}")
    print(f"DRY_RUN: {DRY_RUN}")
    print("=" * 60)

    conn = psycopg2.connect(**kwargs)
    try:
        plaza_name = fetch_plaza_name(conn, plaza)
        if plaza_name is None:
            print(f"WARNING: plaza_identifier {plaza!r} not found in plazas table.")
        else:
            print(f"Plaza name: {plaza_name}")

        total = count_from_class(conn, plaza, from_class)
        conflicts = count_conflicts(conn, plaza, from_class, to_class)
        print(f"Rows with vehicle_class={from_class!r}: {total:,}")
        print(f"Of those, conflict with existing {to_class!r} (same date+hour): {conflicts:,}")
        print(f"Simple rename (no conflict): {total - conflicts:,}")

        if total == 0:
            print("Nothing to update.")
            return 0

        print("Sample rows:")
        for date_v, hour, revenue, txn in sample_rows(conn, plaza, from_class):
            print(f"  {date_v} {hour}: revenue={revenue}, txn_count={txn}")

        if DRY_RUN:
            print("\nDRY_RUN=True — no changes written.")
            return 0

        if not SKIP_CONFIRM:
            answer = input(
                f"\nReplace {total:,} row(s) {from_class!r} → {to_class!r}? [y/N] "
            ).strip()
            if answer.casefold() not in {"y", "yes"}:
                print("Cancelled.")
                return 0

        merged = merge_conflicts(conn, plaza, from_class, to_class) if conflicts else 0
        renamed = rename_remaining(conn, plaza, from_class, to_class)
        conn.commit()

        left = count_from_class(conn, plaza, from_class)
        print("-" * 60)
        print(f"Merged into existing {to_class!r}: {merged:,}")
        print(f"Renamed: {renamed:,}")
        print(f"Remaining {from_class!r} rows: {left:,}")
        print("Done.")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        raise SystemExit(1) from exc
