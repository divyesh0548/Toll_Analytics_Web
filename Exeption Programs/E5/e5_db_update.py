"""
E5 — write matched exception totals into audit_exception_metrics.

Standalone usage (DB update only):
  1. Set DB_UPDATE_ONLY = True
  2. Set MATCHED_OUTPUT_FILE and PLAZA_IDENTIFIER below
  3. python e5_db_update.py

Full pipeline:
  Called automatically from E5_main.py after matched Excel is written.

Update rule when a row already exists for plaza + exception_type_id + year + month:
  update BOTH total_count and total_amount if either new count OR new amount is greater.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# Standalone controls — edit these to run DB update only
# ---------------------------------------------------------------------------
DB_UPDATE_ONLY = True

# Path to e5_matched_*.xlsx (or any Excel with date + potential_exception_value).
MATCHED_OUTPUT_FILE = r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E5\output\e5_matched_20260916_114156.xlsx"

# Target plaza UUID in toll_analytics.plazas / audit_exception_metrics.
PLAZA_IDENTIFIER = "d55c2122-117c-45be-8554-7ea76730932b"

# E05 Incorrect FASTag issuance (seeded id for E05 when catalog inserted 1..12).
EXCEPTION_TYPE_ID = 5

DRY_RUN = False
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
CONFIG_JSON = BASE_DIR / "e5_config.json"
ENV_FILE = BASE_DIR.parent.parent / "Website" / "backend" / ".env"


def load_env() -> None:
    if not ENV_FILE.is_file():
        raise FileNotFoundError(f"Env file not found: {ENV_FILE}")
    load_dotenv(ENV_FILE, override=False)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name} (in {ENV_FILE})")
    return value


def connection_kwargs() -> dict:
    return {
        "host": require_env("DB_HOST"),
        "port": int(require_env("DB_PORT")),
        "user": require_env("DB_USER"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": require_env("DB_NAME"),
    }


def aggregate_monthly_totals(matched_df: pd.DataFrame) -> list[dict]:
    """Group matched rows by year/month from `date`; sum potential_exception_value."""
    if matched_df is None or matched_df.empty:
        return []

    required = {"date", "potential_exception_value"}
    missing = required - set(matched_df.columns)
    if missing:
        raise KeyError(
            f"Matched file missing columns: {sorted(missing)}. "
            f"Available: {list(matched_df.columns)}"
        )

    work = matched_df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date"])
    work["year"] = work["date"].dt.year.astype(int)
    work["month"] = work["date"].dt.month.astype(int)
    work["potential_exception_value"] = pd.to_numeric(
        work["potential_exception_value"],
        errors="coerce",
    ).fillna(0)

    grouped = (
        work.groupby(["year", "month"], as_index=False)
        .agg(
            total_count=("potential_exception_value", "size"),
            total_amount=("potential_exception_value", "sum"),
        )
        .sort_values(["year", "month"])
    )

    rows: list[dict] = []
    for row in grouped.itertuples(index=False):
        rows.append(
            {
                "year": int(row.year),
                "month": int(row.month),
                "total_count": int(row.total_count),
                "total_amount": Decimal(str(row.total_amount)),
            }
        )
    return rows


def fetch_plaza(conn, plaza_identifier: str) -> dict | None:
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT plaza_identifier, plaza_name
            FROM plazas
            WHERE plaza_identifier = %s
            """,
            (plaza_identifier,),
        )
        return cursor.fetchone()


def fetch_existing_metrics(
    conn,
    *,
    plaza_identifier: str,
    exception_type_id: int,
) -> dict[tuple[int, int], dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT year, month, total_count, total_amount
            FROM audit_exception_metrics
            WHERE plaza_identifier = %s
              AND exception_type_id = %s
            """,
            (plaza_identifier, exception_type_id),
        )
        rows = cursor.fetchall()

    return {
        (int(row["year"]), int(row["month"])): {
            "total_count": int(row["total_count"] or 0),
            "total_amount": Decimal(str(row["total_amount"] or 0)),
        }
        for row in rows
    }


def upsert_monthly_metrics(
    conn,
    *,
    plaza_identifier: str,
    exception_type_id: int,
    rows: list[dict],
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Insert missing months.
    Update both total_count and total_amount when either new value is greater.
    """
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}
    if not rows:
        return stats

    existing = fetch_existing_metrics(
        conn,
        plaza_identifier=plaza_identifier,
        exception_type_id=exception_type_id,
    )

    insert_sql = """
        INSERT INTO audit_exception_metrics (
            plaza_identifier,
            exception_type_id,
            year,
            month,
            total_amount,
            total_count,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
    """
    update_sql = """
        UPDATE audit_exception_metrics
        SET total_amount = %s,
            total_count = %s,
            updated_at = NOW()
        WHERE plaza_identifier = %s
          AND exception_type_id = %s
          AND year = %s
          AND month = %s
    """

    with conn.cursor() as cursor:
        for row in rows:
            year = int(row["year"])
            month = int(row["month"])
            new_count = int(row["total_count"] or 0)
            new_amount = Decimal(str(row["total_amount"] or 0))
            key = (year, month)
            current = existing.get(key)

            if current is None:
                print(
                    f"  {year}-{month:02d}: INSERT "
                    f"count={new_count:,}, amount={new_amount:,.2f}"
                )
                if not dry_run:
                    cursor.execute(
                        insert_sql,
                        (
                            plaza_identifier,
                            exception_type_id,
                            year,
                            month,
                            new_amount,
                            new_count,
                        ),
                    )
                stats["inserted"] += 1
                continue

            old_count = int(current["total_count"])
            old_amount = Decimal(str(current["total_amount"]))
            if new_count > old_count or new_amount > old_amount:
                print(
                    f"  {year}-{month:02d}: UPDATE "
                    f"count {old_count:,} -> {new_count:,}, "
                    f"amount {old_amount:,.2f} -> {new_amount:,.2f}"
                )
                if not dry_run:
                    cursor.execute(
                        update_sql,
                        (
                            new_amount,
                            new_count,
                            plaza_identifier,
                            exception_type_id,
                            year,
                            month,
                        ),
                    )
                stats["updated"] += 1
            else:
                print(
                    f"  {year}-{month:02d}: KEEP "
                    f"stored count={old_count:,}, amount={old_amount:,.2f} "
                    f"(new count={new_count:,}, amount={new_amount:,.2f})"
                )
                stats["unchanged"] += 1

    if not dry_run:
        conn.commit()
    return stats


def update_db_from_matched_file(
    matched_file: str | Path,
    plaza_identifier: str,
    *,
    exception_type_id: int = EXCEPTION_TYPE_ID,
    dry_run: bool = False,
) -> dict[str, int]:
    """Read matched Excel, aggregate by month, upsert into audit_exception_metrics."""
    path = Path(matched_file)
    plaza_identifier = str(plaza_identifier or "").strip()
    if not plaza_identifier:
        raise RuntimeError("plaza_identifier is required.")
    if not path.is_file():
        raise FileNotFoundError(f"Matched output file not found: {path}")

    load_env()
    df = pd.read_excel(path)
    rows = aggregate_monthly_totals(df)
    print(f"Matched file: {path}")
    print(f"Plaza: {plaza_identifier}")
    print(f"exception_type_id: {exception_type_id}")
    print(f"Months to sync: {len(rows)}")
    for row in rows:
        print(
            f"  {row['year']}-{row['month']:02d}: "
            f"count={row['total_count']:,}, amount={row['total_amount']:,.2f}"
        )

    conn = psycopg2.connect(**connection_kwargs())
    try:
        plaza = fetch_plaza(conn, plaza_identifier)
        if plaza is None:
            raise RuntimeError(
                f"plaza_identifier {plaza_identifier!r} not found in plazas table."
            )
        print(f"Plaza name: {plaza['plaza_name']}")
        stats = upsert_monthly_metrics(
            conn,
            plaza_identifier=plaza_identifier,
            exception_type_id=exception_type_id,
            rows=rows,
            dry_run=dry_run,
        )
    finally:
        conn.close()

    print(
        f"DB sync done — inserted={stats['inserted']}, "
        f"updated={stats['updated']}, unchanged={stats['unchanged']}"
        + (" (dry run)" if dry_run else "")
    )
    return stats


def update_db_from_dataframe(
    matched_df: pd.DataFrame,
    plaza_identifier: str,
    *,
    exception_type_id: int = EXCEPTION_TYPE_ID,
    dry_run: bool = False,
) -> dict[str, int]:
    """Same upsert as file path, but from an in-memory matched DataFrame."""
    plaza_identifier = str(plaza_identifier or "").strip()
    if not plaza_identifier:
        raise RuntimeError("plaza_identifier is required.")

    load_env()
    rows = aggregate_monthly_totals(matched_df)
    print(f"Plaza: {plaza_identifier}")
    print(f"exception_type_id: {exception_type_id}")
    print(f"Months to sync: {len(rows)}")

    conn = psycopg2.connect(**connection_kwargs())
    try:
        plaza = fetch_plaza(conn, plaza_identifier)
        if plaza is None:
            raise RuntimeError(
                f"plaza_identifier {plaza_identifier!r} not found in plazas table."
            )
        print(f"Plaza name: {plaza['plaza_name']}")
        stats = upsert_monthly_metrics(
            conn,
            plaza_identifier=plaza_identifier,
            exception_type_id=exception_type_id,
            rows=rows,
            dry_run=dry_run,
        )
    finally:
        conn.close()

    print(
        f"DB sync done — inserted={stats['inserted']}, "
        f"updated={stats['updated']}, unchanged={stats['unchanged']}"
        + (" (dry run)" if dry_run else "")
    )
    return stats


def main() -> int:
    if not DB_UPDATE_ONLY:
        print(
            "DB_UPDATE_ONLY is False. Set it True and fill MATCHED_OUTPUT_FILE / "
            "PLAZA_IDENTIFIER to run DB update alone.\n"
            "Or run: python E5_main.py for the full scrape + compare + DB pipeline."
        )
        return 1

    if not str(MATCHED_OUTPUT_FILE).strip():
        raise RuntimeError("Set MATCHED_OUTPUT_FILE at the top of e5_db_update.py.")
    if not str(PLAZA_IDENTIFIER).strip():
        raise RuntimeError("Set PLAZA_IDENTIFIER at the top of e5_db_update.py.")

    update_db_from_matched_file(
        MATCHED_OUTPUT_FILE,
        PLAZA_IDENTIFIER,
        exception_type_id=EXCEPTION_TYPE_ID,
        dry_run=DRY_RUN,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
