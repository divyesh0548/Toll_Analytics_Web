"""
Sync monthly audit exception metrics from the source submissions DB into toll_analytics.

Source rows are filtered by entity_name (submissions.entity_name), aggregated by
calendar month from the date column, then written into audit_exception_metrics for
the given plaza_identifier.

Re-run behavior:
  - Always recalculates monthly totals from source.
  - Inserts a row when plaza + exception + year + month does not exist yet.
  - Updates only when the new total_count is strictly greater than the stored count.
  - Never creates a second row for the same plaza + month (unique constraint).
  - Years listed in SKIP_YEARS are ignored entirely.

END_DATE is inclusive. Rows after END_DATE are ignored, and only complete months
(last day of month <= END_DATE) are written — partial months are skipped.

Configure Website/backend/.env:
  DB_HOST, DB_PORT, DB_USER, DB_PASSWORD
  DB_NAME=toll_analytics
  Source_DB_NAME=snt_form
  exceptions_Table_NAME=submissions

Usage:
  Dry run (totals only):
    Set DRY_RUN = True, ENTITY_NAME, END_DATE
    PLAZA_IDENTIFIER is not required
  Live sync:
    Set DRY_RUN = False, ENTITY_NAME, PLAZA_IDENTIFIER, END_DATE
"""

from __future__ import annotations

import calendar
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# Configuration — update these before running
# ---------------------------------------------------------------------------

# Source submissions.entity_name value for this plaza.
ENTITY_NAME = "madai"

# Target plaza UUID in toll_analytics.plazas.
PLAZA_IDENTIFIER = "d55c2122-117c-45be-8554-7ea76730932b"

# Audit exception code to sync (E01–E12).
EXCEPTION_CODE = "E05"

# Inclusive cutoff (YYYY-MM-DD). Rows after this date are ignored.
# Only complete months (last day of month <= END_DATE) are written,
# so a mid-month cutoff never writes a partial month.
END_DATE = "2026-08-31"

# Years to ignore on this run (and future re-runs). Example: [2024, 2025]
SKIP_YEARS: list[int] = []

# If True: require ENTITY_NAME only, read source totals, print them, write nothing.
# PLAZA_IDENTIFIER is not required in dry run.
DRY_RUN = True

# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / "Website" / "backend" / ".env"


def load_env() -> None:
    if not ENV_FILE.is_file():
        raise FileNotFoundError(f"Env file not found: {ENV_FILE}")
    load_dotenv(ENV_FILE, override=False)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name} (in {ENV_FILE})")
    return value


def connection_kwargs(database: str) -> dict:
    return {
        "host": require_env("DB_HOST"),
        "port": int(require_env("DB_PORT")),
        "user": require_env("DB_USER"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": database,
    }


def parse_end_date(value: str) -> date:
    text = str(value).strip()
    if not text:
        raise RuntimeError("Set END_DATE at the top of this script (YYYY-MM-DD).")
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise RuntimeError(
            f"END_DATE must be YYYY-MM-DD, got {value!r}."
        ) from exc


def month_last_day(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def is_complete_month(year: int, month: int, end_date: date) -> bool:
    """True when the full calendar month is on or before END_DATE."""
    return month_last_day(year, month) <= end_date


def normalize_skip_years(values: list[int]) -> set[int]:
    years: set[int] = set()
    for value in values or []:
        year = int(value)
        if year < 1990 or year > 2100:
            raise RuntimeError(f"SKIP_YEARS contains invalid year: {year}")
        years.add(year)
    return years


def require_config() -> tuple[str, str | None, str, date, set[int]]:
    entity_name = str(ENTITY_NAME).strip()
    plaza_identifier = str(PLAZA_IDENTIFIER).strip()
    exception_code = str(EXCEPTION_CODE).strip().upper()
    end_date = parse_end_date(END_DATE)
    skip_years = normalize_skip_years(SKIP_YEARS)

    if not entity_name:
        raise RuntimeError("Set ENTITY_NAME at the top of this script.")
    if not exception_code:
        raise RuntimeError("Set EXCEPTION_CODE at the top of this script.")

    if DRY_RUN:
        return entity_name, None, exception_code, end_date, skip_years

    if not plaza_identifier or plaza_identifier == "REPLACE_WITH_PLAZA_UUID":
        raise RuntimeError("Set PLAZA_IDENTIFIER at the top of this script.")
    return entity_name, plaza_identifier, exception_code, end_date, skip_years


def fetch_monthly_totals(
    conn,
    table_name: str,
    entity_name: str,
    end_date: date,
) -> list[dict]:
    query = sql.SQL(
        """
        SELECT
            EXTRACT(YEAR FROM date)::int AS year,
            EXTRACT(MONTH FROM date)::int AS month,
            COALESCE(
                SUM(
                    CASE
                        WHEN exceptions IS NULL THEN 0
                        WHEN TRIM(exceptions::text) = '' THEN 0
                        ELSE exceptions::numeric
                    END
                ),
                0
            )::bigint AS total_count,
            COALESCE(
                SUM(
                    CASE
                        WHEN exception_value IS NULL THEN 0
                        WHEN TRIM(exception_value::text) = '' THEN 0
                        ELSE exception_value::numeric
                    END
                ),
                0
            ) AS total_amount
        FROM {table}
        WHERE entity_name = %s
          AND date IS NOT NULL
          AND date <= %s
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    ).format(table=sql.Identifier(table_name))

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(query, (entity_name, end_date.isoformat()))
        return list(cursor.fetchall())


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


def fetch_exception_type_id(conn, exception_code: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM audit_exception_types
            WHERE code = %s AND is_active = TRUE
            """,
            (exception_code,),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            f"Exception type '{exception_code}' not found in audit_exception_types."
        )
    return int(row[0])


def fetch_existing_metrics(
    conn,
    *,
    plaza_identifier: str,
    exception_type_id: int,
) -> dict[tuple[int, int], dict]:
    """Map (year, month) -> existing metric row for this plaza + exception."""
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


def sync_metrics(
    conn,
    *,
    plaza_identifier: str,
    exception_type_id: int,
    rows: list[dict],
    existing: dict[tuple[int, int], dict],
    dry_run: bool,
) -> dict[str, int]:
    """
    Insert missing months; update only when new count is strictly greater.
    Never creates duplicate plaza + month rows.
    """
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}

    if not rows:
        return stats

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
          AND total_count < %s
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
            if new_count > old_count:
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
                            new_count,
                        ),
                    )
                stats["updated"] += 1
            else:
                print(
                    f"  {year}-{month:02d}: KEEP "
                    f"stored count={old_count:,} "
                    f"(source={new_count:,})"
                )
                stats["unchanged"] += 1

    if not dry_run:
        conn.commit()
    return stats


def print_monthly_totals(rows: list[dict]) -> None:
    grand_count = 0
    grand_amount = Decimal("0")
    for row in rows:
        year = int(row["year"])
        month = int(row["month"])
        total_count = int(row["total_count"] or 0)
        total_amount = Decimal(str(row["total_amount"] or 0))
        grand_count += total_count
        grand_amount += total_amount
        print(
            f"  {year}-{month:02d}: count={total_count:,}, amount={total_amount:,.2f}"
        )
    print(
        f"\nTotals across {len(rows)} month(s): "
        f"count={grand_count:,}, amount={grand_amount:,.2f}"
    )


def main() -> int:
    load_env()
    entity_name, plaza_identifier, exception_code, end_date, skip_years = require_config()

    source_db = require_env("Source_DB_NAME")
    table_name = require_env("exceptions_Table_NAME")

    print(f"Source DB: {source_db}.{table_name}")
    print(f"entity_name: {entity_name!r}")
    print(f"Exception code: {exception_code}")
    print(f"End date (inclusive): {end_date.isoformat()}")
    print(
        "SKIP_YEARS: "
        + (", ".join(str(y) for y in sorted(skip_years)) if skip_years else "(none)")
    )
    print("Only complete months on or before END_DATE will be considered.")

    if DRY_RUN:
        print("DRY RUN — source totals only (no plaza_identifier, no writes).")
    else:
        target_db = require_env("DB_NAME")
        print(f"Target DB: {target_db}.audit_exception_metrics")
        print(f"plaza_identifier: {plaza_identifier}")
        print("Existing months update only when source count is higher.")

    with psycopg2.connect(**connection_kwargs(source_db)) as source_conn:
        monthly_rows = fetch_monthly_totals(
            source_conn,
            table_name,
            entity_name,
            end_date,
        )

    complete_rows = [
        row
        for row in monthly_rows
        if is_complete_month(int(row["year"]), int(row["month"]), end_date)
    ]
    skipped_partial = [
        row
        for row in monthly_rows
        if not is_complete_month(int(row["year"]), int(row["month"]), end_date)
    ]
    skipped_years_rows = [
        row for row in complete_rows if int(row["year"]) in skip_years
    ]
    eligible_rows = [
        row for row in complete_rows if int(row["year"]) not in skip_years
    ]

    if skipped_partial:
        print("\nSkipped partial month(s) after END_DATE cutoff:")
        for row in skipped_partial:
            print(f"  {int(row['year'])}-{int(row['month']):02d}")

    if skipped_years_rows:
        print("\nSkipped month(s) in SKIP_YEARS:")
        for row in skipped_years_rows:
            print(f"  {int(row['year'])}-{int(row['month']):02d}")

    if not eligible_rows:
        print(
            f"No eligible months found for entity_name={entity_name!r} "
            f"on or before {end_date.isoformat()}. Nothing to sync."
        )
        return 0

    print(f"\nMonthly totals from source ({len(eligible_rows)} eligible month(s)):")
    print_monthly_totals(eligible_rows)

    if DRY_RUN:
        print("\nDry run complete. No rows written.")
        return 0

    assert plaza_identifier is not None
    target_db = require_env("DB_NAME")

    with psycopg2.connect(**connection_kwargs(target_db)) as target_conn:
        plaza = fetch_plaza(target_conn, plaza_identifier)
        if plaza is None:
            raise RuntimeError(
                f"plaza_identifier {plaza_identifier!r} not found in toll_analytics.plazas."
            )
        exception_type_id = fetch_exception_type_id(target_conn, exception_code)
        existing = fetch_existing_metrics(
            target_conn,
            plaza_identifier=plaza_identifier,
            exception_type_id=exception_type_id,
        )
        print(
            f"\nTarget plaza: {plaza['plaza_name']} "
            f"({plaza['plaza_identifier']})"
        )
        print(f"Existing metric months: {len(existing)}")

        stats = sync_metrics(
            target_conn,
            plaza_identifier=plaza_identifier,
            exception_type_id=exception_type_id,
            rows=eligible_rows,
            existing=existing,
            dry_run=False,
        )

    print(
        f"\nApplied for {exception_code}: "
        f"inserted={stats['inserted']}, "
        f"updated={stats['updated']}, "
        f"unchanged={stats['unchanged']}."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        raise SystemExit(1)
