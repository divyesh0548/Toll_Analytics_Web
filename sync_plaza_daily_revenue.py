"""
Sync daily plaza revenue from the source submissions DB into toll_analytics.

Source rows are filtered by entity_name (submissions.entity_name), aggregated by
calendar day from the date column (SUM of revenue), then written into
plaza_daily_revenue for the given plaza_identifier.

Re-run behavior:
  - Always recalculates daily totals from source.
  - Inserts a row when plaza + date does not exist yet.
  - Updates only when the new revenue is strictly greater than the stored value.
  - Never creates a second row for the same plaza + date (unique constraint).
  - Years listed in SKIP_YEARS are ignored entirely.

END_DATE is inclusive. Rows after END_DATE are ignored.

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
ENTITY_NAME = "aroli"

# Target plaza UUID in toll_analytics.plazas.
PLAZA_IDENTIFIER = "39d45059-341d-435b-8824-9963b4e2068e"

# Inclusive cutoff (YYYY-MM-DD). Rows after this date are ignored.
END_DATE = "2026-08-31"

# Years to ignore on this run (and future re-runs). Example: [2024, 2025]
SKIP_YEARS: list[int] = []

# If True: require ENTITY_NAME only, read source totals, print them, write nothing.
# PLAZA_IDENTIFIER is not required in dry run.
DRY_RUN = False

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


def normalize_skip_years(values: list[int]) -> set[int]:
    years: set[int] = set()
    for value in values or []:
        year = int(value)
        if year < 1990 or year > 2100:
            raise RuntimeError(f"SKIP_YEARS contains invalid year: {year}")
        years.add(year)
    return years


def require_config() -> tuple[str, str | None, date, set[int]]:
    entity_name = str(ENTITY_NAME).strip()
    plaza_identifier = str(PLAZA_IDENTIFIER).strip()
    end_date = parse_end_date(END_DATE)
    skip_years = normalize_skip_years(SKIP_YEARS)

    if not entity_name:
        raise RuntimeError("Set ENTITY_NAME at the top of this script.")

    if DRY_RUN:
        return entity_name, None, end_date, skip_years

    if not plaza_identifier or plaza_identifier == "REPLACE_WITH_PLAZA_UUID":
        raise RuntimeError("Set PLAZA_IDENTIFIER at the top of this script.")
    return entity_name, plaza_identifier, end_date, skip_years


def fetch_daily_totals(
    conn,
    table_name: str,
    entity_name: str,
    end_date: date,
) -> list[dict]:
    query = sql.SQL(
        """
        SELECT
            date::date AS day,
            COALESCE(
                SUM(
                    CASE
                        WHEN revenue IS NULL THEN 0
                        WHEN TRIM(revenue::text) = '' THEN 0
                        ELSE revenue::numeric
                    END
                ),
                0
            ) AS revenue
        FROM {table}
        WHERE entity_name = %s
          AND date IS NOT NULL
          AND date <= %s
        GROUP BY 1
        ORDER BY 1
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


def fetch_existing_revenue(conn, plaza_identifier: str) -> dict[date, Decimal]:
    """Map date -> stored revenue for this plaza."""
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT date, revenue
            FROM plaza_daily_revenue
            WHERE plaza_identifier = %s
            """,
            (plaza_identifier,),
        )
        rows = cursor.fetchall()

    result: dict[date, Decimal] = {}
    for row in rows:
        day = row["date"]
        if hasattr(day, "date"):
            day = day.date()
        result[day] = Decimal(str(row["revenue"] or 0))
    return result


def sync_revenue(
    conn,
    *,
    plaza_identifier: str,
    rows: list[dict],
    existing: dict[date, Decimal],
    dry_run: bool,
) -> dict[str, int]:
    """
    Insert missing days; update only when new revenue is strictly greater.
    Never creates duplicate plaza + date rows.
    """
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}

    if not rows:
        return stats

    insert_sql = """
        INSERT INTO plaza_daily_revenue (
            plaza_identifier,
            date,
            revenue,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, NOW(), NOW())
    """
    update_sql = """
        UPDATE plaza_daily_revenue
        SET revenue = %s,
            updated_at = NOW()
        WHERE plaza_identifier = %s
          AND date = %s
          AND revenue < %s
    """

    with conn.cursor() as cursor:
        for row in rows:
            day = row["day"]
            if hasattr(day, "date"):
                day = day.date()
            new_revenue = Decimal(str(row["revenue"] or 0))
            current = existing.get(day)

            if current is None:
                print(f"  {day.isoformat()}: INSERT revenue={new_revenue:,.2f}")
                if not dry_run:
                    cursor.execute(
                        insert_sql,
                        (plaza_identifier, day.isoformat(), new_revenue),
                    )
                stats["inserted"] += 1
                continue

            if new_revenue > current:
                print(
                    f"  {day.isoformat()}: UPDATE "
                    f"revenue {current:,.2f} -> {new_revenue:,.2f}"
                )
                if not dry_run:
                    cursor.execute(
                        update_sql,
                        (
                            new_revenue,
                            plaza_identifier,
                            day.isoformat(),
                            new_revenue,
                        ),
                    )
                stats["updated"] += 1
            else:
                print(
                    f"  {day.isoformat()}: KEEP "
                    f"stored revenue={current:,.2f} "
                    f"(source={new_revenue:,.2f})"
                )
                stats["unchanged"] += 1

    if not dry_run:
        conn.commit()
    return stats


def print_daily_totals(rows: list[dict]) -> None:
    grand = Decimal("0")
    for row in rows:
        day = row["day"]
        if hasattr(day, "date"):
            day = day.date()
        revenue = Decimal(str(row["revenue"] or 0))
        grand += revenue
        print(f"  {day.isoformat()}: revenue={revenue:,.2f}")
    print(f"\nTotals across {len(rows)} day(s): revenue={grand:,.2f}")


def main() -> int:
    load_env()
    entity_name, plaza_identifier, end_date, skip_years = require_config()

    source_db = require_env("Source_DB_NAME")
    table_name = require_env("exceptions_Table_NAME")

    print(f"Source DB: {source_db}.{table_name}")
    print(f"entity_name: {entity_name!r}")
    print(f"End date (inclusive): {end_date.isoformat()}")
    print(
        "SKIP_YEARS: "
        + (", ".join(str(y) for y in sorted(skip_years)) if skip_years else "(none)")
    )

    if DRY_RUN:
        print("DRY RUN — source totals only (no plaza_identifier, no writes).")
    else:
        target_db = require_env("DB_NAME")
        print(f"Target DB: {target_db}.plaza_daily_revenue")
        print(f"plaza_identifier: {plaza_identifier}")
        print("Existing days update only when source revenue is higher.")

    with psycopg2.connect(**connection_kwargs(source_db)) as source_conn:
        daily_rows = fetch_daily_totals(
            source_conn,
            table_name,
            entity_name,
            end_date,
        )

    skipped_years_rows = []
    eligible_rows = []
    for row in daily_rows:
        day = row["day"]
        if hasattr(day, "date"):
            day = day.date()
        if day.year in skip_years:
            skipped_years_rows.append(row)
        else:
            eligible_rows.append(row)

    if skipped_years_rows:
        print("\nSkipped day(s) in SKIP_YEARS:")
        for row in skipped_years_rows:
            day = row["day"]
            if hasattr(day, "date"):
                day = day.date()
            print(f"  {day.isoformat()}")

    if not eligible_rows:
        print(
            f"No eligible days found for entity_name={entity_name!r} "
            f"on or before {end_date.isoformat()}. Nothing to sync."
        )
        return 0

    print(f"\nDaily revenue from source ({len(eligible_rows)} eligible day(s)):")
    print_daily_totals(eligible_rows)

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
        existing = fetch_existing_revenue(target_conn, plaza_identifier)
        print(
            f"\nTarget plaza: {plaza['plaza_name']} "
            f"({plaza['plaza_identifier']})"
        )
        print(f"Existing revenue days: {len(existing)}")

        stats = sync_revenue(
            target_conn,
            plaza_identifier=plaza_identifier,
            rows=eligible_rows,
            existing=existing,
            dry_run=False,
        )

    print(
        f"\nApplied: "
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
