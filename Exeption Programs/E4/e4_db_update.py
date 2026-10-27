"""
E4 — aggregate Loss / Trips by Start-date month and upsert audit_exception_metrics.

Standalone usage (DB update only):
  1. Set DB_UPDATE_ONLY = True
  2. Set MERGED_OUTPUT_FILE and PLAZA_IDENTIFIER below
  3. python e4_db_update.py

Full pipeline:
  Called from E4_main.py after Loss is computed.

Update rule when a row already exists for plaza + exception_type_id + year + month:
  always overwrite total_count and total_amount with the new values.
  Optional status / notes (e.g. empty_filter when all rows dropped).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# Standalone controls — edit these to run DB update only
# ---------------------------------------------------------------------------
DB_UPDATE_ONLY = False

MERGED_OUTPUT_FILE = (
    r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E4\output\merged_pass_files.xlsx"
)

PLAZA_IDENTIFIER = ""

# E04 Local passes wrongly issued to commercial vehicles
EXCEPTION_TYPE_ID = 4

DRY_RUN = False
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
WEBSITE_ENV = BASE_DIR.parent.parent / "Website" / "backend" / ".env"

# Column alias lists (kept local so this module can run standalone)
START_DATE_ALIASES = [
    "Validity Start Date",
    "Start Date",
    "Start Effective Date",
    "Pass Start Date",
    "Valid From",
]
END_DATE_ALIASES = [
    "Validity End Date",
    "End Date",
    "End Effective Date",
    "Pass End Date",
    "Valid To",
]
LOSS_ALIASES = ["Loss"]
TRIPS_ALIASES = ["Trips taken", "Trip taken"]


def load_env() -> None:
    """Prefer process env (Docker) / Website/backend/.env; E4/.env is optional."""
    loaded_any = False
    backend_root = os.environ.get("WEBSITE_BACKEND_ROOT", "").strip()
    candidates = []
    if backend_root:
        candidates.append(Path(backend_root).expanduser() / ".env")
    candidates.extend([WEBSITE_ENV, ENV_FILE])
    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=False)
            loaded_any = True
    if loaded_any:
        return
    if os.getenv("DB_HOST", "").strip() and (
        os.getenv("Toll_Analytics_DB", "").strip()
        or os.getenv("DB_NAME", "").strip()
    ):
        return
    raise FileNotFoundError(
        f"Env file not found: tried {WEBSITE_ENV} and {ENV_FILE}"
    )


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required env var: {name} "
            "(checked process env, Website/backend/.env, E4/.env)"
        )
    return value


def metrics_table_name() -> str:
    return (
        os.getenv("Exception_Metrics_Table", "").strip()
        or os.getenv("EXCEPTION_METRICS_TABLE", "").strip()
        or "audit_exception_metrics"
    )


def connection_kwargs() -> dict:
    """Connect to analytics metrics DB (Toll_Analytics_DB), not submissions."""
    database = (
        os.getenv("Toll_Analytics_DB", "").strip()
        or os.getenv("DB_NAME", "").strip()
    )
    if not database:
        raise RuntimeError("Missing Toll_Analytics_DB / DB_NAME")
    return {
        "host": require_env("DB_HOST"),
        "port": int(os.getenv("DB_PORT") or "5432"),
        "user": require_env("DB_USER"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": database,
    }


def _normalize_header_key(value) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\u00a0", " ").strip().lower()
    return " ".join(text.split())


def resolve_column(headers: list[str], aliases: list[str]) -> str | None:
    by_key = {_normalize_header_key(h): h for h in headers if str(h).strip()}
    for alias in aliases or []:
        key = _normalize_header_key(alias)
        if key in by_key:
            return by_key[key]
    return None


_PASS_DATE_ORDERS = {"dd/mm/yyyy", "mm/dd/yyyy", "dd-mmm-yyyy"}
_BLANK_PASS_DATE = {"", "na", "n/a", "null", "none", "nat", "nan", "-"}
_PASS_DAY_FIRST = (
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y",
    "%d/%m/%Y",
)
_PASS_MONTH_FIRST = (
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m-%d-%Y %H:%M:%S",
    "%m-%d-%Y %H:%M",
    "%m/%d/%Y",
    "%m-%d-%Y",
)
_PASS_NAMED_MONTH = (
    "%d-%b-%Y %I:%M:%S %p",
    "%d-%b-%Y %I:%M %p",
    "%d-%b-%Y %H:%M:%S",
    "%d-%b-%Y",
)
_PASS_ISO = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def parse_ordered_datetime_series(series: pd.Series, date_order: str) -> pd.Series:
    """Parse pass-file dates. 18-03-2026 00:00:00 is dd/mm/yyyy, not month-first."""
    order = str(date_order or "").strip().casefold()
    if order == "mm/dd/yyyy":
        formats = _PASS_MONTH_FIRST + _PASS_ISO + _PASS_NAMED_MONTH
        dayfirst = False
    elif order == "dd-mmm-yyyy":
        formats = _PASS_NAMED_MONTH + _PASS_ISO
        dayfirst = True
    else:
        formats = _PASS_DAY_FIRST + _PASS_ISO + _PASS_NAMED_MONTH
        dayfirst = True

    def one(value):
        text = "" if value is None else str(value).strip()
        if text.casefold() in _BLANK_PASS_DATE:
            return pd.NaT
        for fmt in formats:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        parsed = pd.to_datetime(text, dayfirst=dayfirst, errors="coerce")
        if pd.isna(parsed):
            return pd.NaT
        return parsed.to_pydatetime()

    return pd.to_datetime(series.map(one), errors="coerce")


def aggregate_monthly_loss_and_trips(
    pass_df: pd.DataFrame,
    *,
    start_date_aliases: list[str] | None = None,
    end_date_aliases: list[str] | None = None,
    loss_aliases: list[str] | None = None,
    trips_aliases: list[str] | None = None,
    date_order: str | None = None,
    only_nonzero_trips: bool = False,
) -> list[dict]:
    """
    Group by year/month of the pass start date.
    total_amount = sum of positive Loss only (negatives ignored);
    total_count = sum(Trips taken).
    end_date_aliases is accepted and ignored so older callers still run.
    Does not change Loss values in the output file — metrics only.
    """
    if pass_df is None or pass_df.empty:
        return []

    headers = [str(c) for c in pass_df.columns]
    start_col = resolve_column(headers, start_date_aliases or START_DATE_ALIASES)
    loss_col = resolve_column(headers, loss_aliases or LOSS_ALIASES)
    trips_col = resolve_column(headers, trips_aliases or TRIPS_ALIASES)

    missing = []
    if not start_col:
        missing.append("start date")
    if not loss_col:
        missing.append("Loss")
    if not trips_col:
        missing.append("Trips taken")
    if missing:
        raise KeyError(
            f"Merged pass file missing columns: {missing}. "
            f"Available: {list(pass_df.columns)}"
        )

    work = pass_df.copy()
    if date_order:
        work["_start"] = parse_ordered_datetime_series(work[start_col], date_order)
    else:
        work["_start"] = pd.to_datetime(work[start_col], errors="coerce")
    work = work.dropna(subset=["_start"])
    if work.empty:
        return []

    work["year"] = work["_start"].dt.year.astype(int)
    work["month"] = work["_start"].dt.month.astype(int)
    # Metrics: only positive Loss contributes to total_amount.
    work["_loss"] = (
        pd.to_numeric(work[loss_col], errors="coerce").fillna(0).clip(lower=0)
    )
    work["_trips"] = pd.to_numeric(work[trips_col], errors="coerce").fillna(0)
    if only_nonzero_trips:
        work = work.loc[work["_trips"] != 0].copy()
        if work.empty:
            return []

    grouped = (
        work.groupby(["year", "month"], as_index=False)
        .agg(
            total_amount=("_loss", "sum"),
            total_count=("_trips", "sum"),
        )
        .sort_values(["year", "month"])
    )

    rows: list[dict] = []
    for row in grouped.itertuples(index=False):
        rows.append(
            {
                "year": int(row.year),
                "month": int(row.month),
                "total_count": int(round(float(row.total_count))),
                "total_amount": Decimal(str(round(float(row.total_amount), 2))),
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
    table_name: str | None = None,
) -> dict[tuple[int, int], dict]:
    table = sql.Identifier(table_name or metrics_table_name())
    query = sql.SQL(
        """
        SELECT year, month, total_count, total_amount
        FROM {table}
        WHERE plaza_identifier = %s
          AND exception_type_id = %s
        """
    ).format(table=table)
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(query, (plaza_identifier, exception_type_id))
        rows = cursor.fetchall()

    return {
        (int(row["year"]), int(row["month"])): {
            "total_count": int(row["total_count"] or 0),
            "total_amount": Decimal(str(row["total_amount"] or 0)),
        }
        for row in rows
    }


EMPTY_FILTER_STATUS = "empty_filter"
EMPTY_FILTER_NOTES = "No qualifying passes after filters"


def upsert_monthly_metrics(
    conn,
    *,
    plaza_identifier: str,
    exception_type_id: int,
    rows: list[dict],
    dry_run: bool = False,
    table_name: str | None = None,
) -> dict[str, int]:
    """
    Insert missing months.
    Always overwrite total_count and total_amount when a row already exists.
    Optional per-row status / notes (cleared when omitted / null).
    """
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}
    if not rows:
        return stats

    table = table_name or metrics_table_name()
    table_id = sql.Identifier(table)

    existing = fetch_existing_metrics(
        conn,
        plaza_identifier=plaza_identifier,
        exception_type_id=exception_type_id,
        table_name=table,
    )

    insert_sql = sql.SQL(
        """
        INSERT INTO {table} (
            plaza_identifier,
            exception_type_id,
            year,
            month,
            total_amount,
            total_count,
            status,
            notes,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """
    ).format(table=table_id)
    update_sql = sql.SQL(
        """
        UPDATE {table}
        SET total_amount = %s,
            total_count = %s,
            status = %s,
            notes = %s,
            updated_at = NOW()
        WHERE plaza_identifier = %s
          AND exception_type_id = %s
          AND year = %s
          AND month = %s
        """
    ).format(table=table_id)

    with conn.cursor() as cursor:
        for row in rows:
            year = int(row["year"])
            month = int(row["month"])
            new_count = int(row["total_count"] or 0)
            new_amount = Decimal(str(row["total_amount"] or 0))
            status = row.get("status")
            notes = row.get("notes")
            if status is not None:
                status = str(status).strip() or None
            if notes is not None:
                notes = str(notes).strip() or None
            key = (year, month)
            current = existing.get(key)

            if current is None:
                print(
                    f"  {year}-{month:02d}: INSERT "
                    f"count={new_count:,}, amount={new_amount:,.2f}"
                    + (f", status={status}" if status else "")
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
                            status,
                            notes,
                        ),
                    )
                stats["inserted"] += 1
                continue

            old_count = int(current["total_count"])
            old_amount = Decimal(str(current["total_amount"]))
            print(
                f"  {year}-{month:02d}: UPDATE "
                f"count {old_count:,} -> {new_count:,}, "
                f"amount {old_amount:,.2f} -> {new_amount:,.2f}"
                + (f", status={status}" if status else "")
            )
            if not dry_run:
                cursor.execute(
                    update_sql,
                    (
                        new_amount,
                        new_count,
                        status,
                        notes,
                        plaza_identifier,
                        exception_type_id,
                        year,
                        month,
                    ),
                )
            stats["updated"] += 1

    if not dry_run:
        conn.commit()
    return stats


def zero_month_rows(
    periods: list[tuple[int, int]],
    *,
    status: str = EMPTY_FILTER_STATUS,
    notes: str = EMPTY_FILTER_NOTES,
) -> list[dict]:
    """Build metric rows with count/amount 0 for each (year, month)."""
    rows: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for year, month in periods:
        key = (int(year), int(month))
        if key in seen or not (1 <= key[1] <= 12):
            continue
        seen.add(key)
        rows.append(
            {
                "year": key[0],
                "month": key[1],
                "total_count": 0,
                "total_amount": Decimal("0"),
                "status": status,
                "notes": notes,
            }
        )
    return rows


def update_db_zero_months(
    periods: list[tuple[int, int]],
    plaza_identifier: str,
    *,
    exception_type_id: int = EXCEPTION_TYPE_ID,
    dry_run: bool = False,
    status: str = EMPTY_FILTER_STATUS,
    notes: str = EMPTY_FILTER_NOTES,
) -> dict[str, int]:
    """Upsert zero metrics (with status/notes) for plaza months with no E4 output."""
    plaza_identifier = str(plaza_identifier or "").strip()
    if not plaza_identifier:
        raise RuntimeError("plaza_identifier is required.")
    rows = zero_month_rows(periods, status=status, notes=notes)
    if not rows:
        print("No months to mark as empty — DB not updated.")
        return {"inserted": 0, "updated": 0, "unchanged": 0}

    load_env()
    conn_kw = connection_kwargs()
    table = metrics_table_name()
    print(f"Target DB: {conn_kw['database']}.{table}")
    print(f"Plaza: {plaza_identifier}")
    print(f"exception_type_id: {exception_type_id}")
    print(f"Marking {len(rows)} month(s) as empty after filters:")
    for row in rows:
        print(f"  {row['year']}-{row['month']:02d}: count=0, amount=0, status={row['status']}")

    conn = psycopg2.connect(**conn_kw)
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
            table_name=table,
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
    pass_df: pd.DataFrame,
    plaza_identifier: str,
    *,
    exception_type_id: int = EXCEPTION_TYPE_ID,
    dry_run: bool = False,
    start_date_aliases: list[str] | None = None,
    end_date_aliases: list[str] | None = None,
    loss_aliases: list[str] | None = None,
    trips_aliases: list[str] | None = None,
    date_order: str | None = None,
    only_nonzero_trips: bool = False,
) -> dict[str, int]:
    plaza_identifier = str(plaza_identifier or "").strip()
    if not plaza_identifier:
        raise RuntimeError("plaza_identifier is required.")

    load_env()
    conn_kw = connection_kwargs()
    table = metrics_table_name()
    rows = aggregate_monthly_loss_and_trips(
        pass_df,
        start_date_aliases=start_date_aliases or end_date_aliases,
        loss_aliases=loss_aliases,
        trips_aliases=trips_aliases,
        date_order=date_order,
        only_nonzero_trips=only_nonzero_trips,
    )
    print(f"Target DB: {conn_kw['database']}.{table}")
    print(f"Plaza: {plaza_identifier}")
    print(f"exception_type_id: {exception_type_id}")
    print(f"Months to sync: {len(rows)}")
    for row in rows:
        print(
            f"  {row['year']}-{row['month']:02d}: "
            f"trips(total_count)={row['total_count']:,}, "
            f"loss(total_amount)={row['total_amount']:,.2f}"
        )

    conn = psycopg2.connect(**conn_kw)
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
            table_name=table,
        )
    finally:
        conn.close()

    print(
        f"DB sync done — inserted={stats['inserted']}, "
        f"updated={stats['updated']}, unchanged={stats['unchanged']}"
        + (" (dry run)" if dry_run else "")
    )
    return stats


def update_db_from_merged_file(
    merged_file: str | Path,
    plaza_identifier: str,
    *,
    exception_type_id: int = EXCEPTION_TYPE_ID,
    dry_run: bool = False,
) -> dict[str, int]:
    path = Path(merged_file)
    if not path.is_file():
        raise FileNotFoundError(f"Merged output file not found: {path}")
    df = pd.read_excel(path)
    print(f"Merged file: {path}")
    return update_db_from_dataframe(
        df,
        plaza_identifier,
        exception_type_id=exception_type_id,
        dry_run=dry_run,
    )


def main() -> int:
    if not DB_UPDATE_ONLY:
        print(
            "DB_UPDATE_ONLY is False. Set it True and fill MERGED_OUTPUT_FILE / "
            "PLAZA_IDENTIFIER to run DB update alone.\n"
            "Or run: python E4_main.py for the full pipeline."
        )
        return 1

    if not str(MERGED_OUTPUT_FILE).strip():
        raise RuntimeError("Set MERGED_OUTPUT_FILE at the top of e4_db_update.py.")
    if not str(PLAZA_IDENTIFIER).strip():
        raise RuntimeError("Set PLAZA_IDENTIFIER at the top of e4_db_update.py.")

    update_db_from_merged_file(
        MERGED_OUTPUT_FILE,
        PLAZA_IDENTIFIER,
        exception_type_id=EXCEPTION_TYPE_ID,
        dry_run=DRY_RUN,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
