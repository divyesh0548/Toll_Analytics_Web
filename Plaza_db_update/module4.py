"""
Module 4 — Standalone ETC revenue by vehicle class (hourly).

1. Download ETC files from submissions DB (`etc_file_url`), save under
   DOWNLOAD_FOLDER / {entity_name} / {date} / …
2. For each file: map NPCI Class Desc → canonical vehicle class (same as VRN),
   bucket Reader Read Time into hour labels, SUM Settlement Amount
   (negatives subtract; zeros included).
3. Upsert into revenue_distribution_per_class.
   Unique: (plaza_identifier, date, hour, vehicle_class).
   On conflict: overwrite only when the new revenue is greater.

Hard-stop if any NPCI class is not in vehicle_class.json aliases.

Edit runtime inputs below, then:
  python module4.py
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd
import psycopg2
import requests
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor, execute_values

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from config.db import (  # noqa: E402
    ensure_revenue_distribution_per_class_table,
    get_analytics_db_connection_kwargs,
    load_env_file,
)
from config.excel_config import (  # noqa: E402
    ETC_DATETIME_COLUMN_ALIASES,
    ETC_NPCI_CLASS_COLUMN_ALIASES,
    ETC_REQUIRED_FIELDS,
    ETC_SETTLEMENT_COLUMN_ALIASES,
    EXCEL_EXTENSIONS,
)
from config.settings import (  # noqa: E402
    PLAZA_IDENTIFIER,
    PLAZA_NAME,
    REVENUE_DISTRIBUTION_PER_CLASS_TABLE,
    START_DATE_LIMIT_DATE,
)
from excel_common import (  # noqa: E402
    UnmappedValueError,
    detect_datetime_format,
    find_column_by_aliases,
    hour_bucket_label,
    is_blank,
    is_skippable_excel_read_error,
    read_excel_file,
    safe_parse_datetime,
    try_normalize_vehicle_class,
    try_parse_datetime,
)

# ---------------------------------------------------------------------------
# Runtime inputs
# ---------------------------------------------------------------------------

ENTITY_NAME = PLAZA_NAME  # submissions.entity_name (usually same as plaza folder name)
FROM_DATE = "2025-11-23"  # inclusive YYYY-MM-DD
TO_DATE = "2026-08-31"  # inclusive YYYY-MM-DD

DOWNLOAD_FOLDER = ROOT_DIR / "etc_downloads"
DOWNLOAD_TIMEOUT_SECONDS = 180
SKIP_EXISTING = True
DRY_RUN = False

SUBMISSIONS_TABLE = "submissions"

DATA_COLUMNS = [
    "plaza_identifier",
    "plaza_name",
    "date",
    "hour",
    "vehicle_class",
    "revenue",
    "txn_count",
]
KEY_COLUMNS = ["plaza_identifier", "date", "hour", "vehicle_class"]

E4_ENV = ROOT_DIR.parent / "Exeption Programs" / "E4" / ".env"
WEBSITE_ENV = ROOT_DIR.parent / "Website" / "backend" / ".env"


def require_plaza_settings() -> None:
    if not PLAZA_IDENTIFIER or PLAZA_IDENTIFIER == "REPLACE_WITH_PLAZA_UUID":
        raise RuntimeError(
            "Set PLAZA_IDENTIFIER in Plaza_db_update/config/settings.py "
            "to the plaza UUID from the website."
        )
    if not PLAZA_NAME or not str(PLAZA_NAME).strip():
        raise RuntimeError("Set PLAZA_NAME in Plaza_db_update/config/settings.py.")


def load_all_env() -> None:
    load_env_file()
    for path in (ROOT_DIR / ".env", E4_ENV, WEBSITE_ENV):
        if path.is_file():
            load_dotenv(path, override=False)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def submissions_db_kwargs() -> dict:
    """Submissions DB (ETC URLs) — same keys as E4 / VRN downloader."""
    return {
        "host": require_env("DB_HOST"),
        "port": int(os.getenv("DB_PORT", "5432").strip() or "5432"),
        "user": require_env("DB_USER"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": require_env("DB_NAME"),
    }


def submissions_table_name() -> str:
    return (
        os.getenv("Table_NAME", "").strip()
        or os.getenv("TABLE_NAME", "").strip()
        or SUBMISSIONS_TABLE
    )


def parse_iso_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise RuntimeError(f"{label} must be YYYY-MM-DD, got {value!r}") from exc


def validate_interval(from_date: str, to_date: str) -> tuple[date, date]:
    start = parse_iso_date(from_date, "FROM_DATE")
    end = parse_iso_date(to_date, "TO_DATE")
    if end < start:
        raise RuntimeError("TO_DATE must be on or after FROM_DATE.")
    return start, end


def fetch_etc_records(
    conn,
    *,
    entity_name: str,
    start: date,
    end: date,
) -> list[dict]:
    query = sql.SQL(
        """
        SELECT id, entity_name, date, shift, etc_file_url
        FROM {table}
        WHERE entity_name = %s
          AND date::date >= %s
          AND date::date <= %s
          AND etc_file_url IS NOT NULL
          AND TRIM(etc_file_url::text) <> ''
        ORDER BY date, shift, id
        """
    ).format(table=sql.Identifier(submissions_table_name()))

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(query, (entity_name, start.isoformat(), end.isoformat()))
        return [dict(row) for row in cursor.fetchall()]


def filename_from_url(url: str, record_id: int) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if name:
        return name
    return f"etc_{record_id}.xlsx"


def safe_part(value) -> str:
    text = str(value).strip() if value not in (None, "") else "unknown"
    return re.sub(r'[\\/:*?"<>|]+', "-", text)


def build_local_path(
    output_folder: Path,
    entity_name: str,
    record_date,
    shift,
    filename: str,
) -> Path:
    if hasattr(record_date, "strftime"):
        date_str = record_date.strftime("%Y-%m-%d")
    else:
        date_str = str(record_date)[:10]
    return (
        output_folder
        / safe_part(entity_name)
        / date_str
        / safe_part(shift if shift not in (None, "") else "unknown_shift")
        / filename
    )


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()
    destination.write_bytes(response.content)


def parse_settlement_amount(value) -> Decimal:
    """Parse amount; blanks → 0. Negatives kept (subtract from total)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal("0")
    text = str(value).strip().replace(",", "")
    if not text or text.casefold() in {"nan", "none", "null", "-"}:
        return Decimal("0")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def validate_etc_dataframe(df: pd.DataFrame, file_name: str, datetime_format: str) -> None:
    dt_col = find_column_by_aliases(df, ETC_DATETIME_COLUMN_ALIASES)
    npci_col = find_column_by_aliases(df, ETC_NPCI_CLASS_COLUMN_ALIASES)
    # Settlement column presence checked; amounts always parseable to 0
    find_column_by_aliases(df, ETC_SETTLEMENT_COLUMN_ALIASES)

    invalid_datetimes: dict[str, int] = {}
    unmapped_classes: dict[str, int] = {}

    for _, row in df.iterrows():
        dt_raw = row[dt_col]
        if not is_blank(dt_raw):
            if try_parse_datetime(dt_raw, datetime_format=datetime_format) is None:
                key = str(dt_raw).strip()
                invalid_datetimes[key] = invalid_datetimes.get(key, 0) + 1

        npci_raw = row[npci_col]
        if not is_blank(npci_raw):
            if try_normalize_vehicle_class(npci_raw) is None:
                key = str(npci_raw).strip()
                unmapped_classes[key] = unmapped_classes.get(key, 0) + 1

    errors: list[str] = []
    if invalid_datetimes:
        sample = ", ".join(
            f"{k!r} ({c})" for k, c in sorted(invalid_datetimes.items())[:8]
        )
        errors.append(f"Invalid Reader Read Time in '{file_name}': {sample}")
    if unmapped_classes:
        sample = ", ".join(
            f"{k!r} ({c} row(s))" for k, c in sorted(unmapped_classes.items())
        )
        errors.append(
            f"Unmapped NPCI Class Desc in '{file_name}' "
            f"(add aliases to vehicle_class.json): {sample}"
        )
    if errors:
        raise UnmappedValueError("\n".join(errors))


def prepare_etc_dataframe(df: pd.DataFrame, datetime_format: str) -> pd.DataFrame:
    dt_col = find_column_by_aliases(df, ETC_DATETIME_COLUMN_ALIASES)
    npci_col = find_column_by_aliases(df, ETC_NPCI_CLASS_COLUMN_ALIASES)
    amt_col = find_column_by_aliases(df, ETC_SETTLEMENT_COLUMN_ALIASES)

    event_values = [
        safe_parse_datetime(value, datetime_format=datetime_format)
        for value in df[dt_col]
    ]
    prepared = pd.DataFrame()
    prepared["event_dt"] = pd.to_datetime(event_values, errors="coerce")
    prepared["vehicle_class"] = df[npci_col].map(
        lambda v: try_normalize_vehicle_class(v) if not is_blank(v) else None
    )
    prepared["amount"] = df[amt_col].map(parse_settlement_amount)

    prepared = prepared[prepared["event_dt"].notna()].copy()
    prepared = prepared[prepared["vehicle_class"].notna()].copy()
    prepared["hour"] = prepared["event_dt"].map(hour_bucket_label)
    prepared["date"] = prepared["event_dt"].dt.date
    prepared = prepared[prepared["date"] >= START_DATE_LIMIT_DATE].copy()
    return prepared


def aggregate_hourly_revenue(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    grouped = (
        df.groupby(["date", "hour", "vehicle_class"], sort=True)
        .agg(revenue=("amount", "sum"), txn_count=("amount", "size"))
        .reset_index()
    )
    rows: list[dict] = []
    for record in grouped.itertuples(index=False):
        revenue = record.revenue
        if isinstance(revenue, Decimal):
            revenue_val = revenue
        else:
            revenue_val = Decimal(str(revenue))
        rows.append(
            {
                "plaza_identifier": PLAZA_IDENTIFIER,
                "plaza_name": PLAZA_NAME,
                "date": record.date,
                "hour": record.hour,
                "vehicle_class": record.vehicle_class,
                "revenue": round(revenue_val, 2),
                "txn_count": int(record.txn_count),
            }
        )
    return rows


def merge_into_accumulator(acc: dict[tuple, dict], rows: list[dict]) -> list[tuple]:
    """Sum revenue/txn_count into acc; return keys touched."""
    touched: list[tuple] = []
    for row in rows:
        key = (row["date"], row["hour"], row["vehicle_class"])
        if key not in acc:
            acc[key] = {
                "plaza_identifier": row["plaza_identifier"],
                "plaza_name": row["plaza_name"],
                "date": row["date"],
                "hour": row["hour"],
                "vehicle_class": row["vehicle_class"],
                "revenue": Decimal("0"),
                "txn_count": 0,
            }
        acc[key]["revenue"] += Decimal(str(row["revenue"]))
        acc[key]["txn_count"] += int(row["txn_count"])
        touched.append(key)
    return touched


def upsert_revenue_if_greater(conn, rows: list[dict]) -> tuple[int, int]:
    """
    Insert new keys. On conflict, update only when EXCLUDED.revenue > existing.
    txn_count follows revenue when updated.
    """
    if not rows:
        return 0, 0

    values = []
    for row in rows:
        revenue = row["revenue"]
        if isinstance(revenue, Decimal):
            revenue = float(revenue)
        else:
            revenue = float(revenue)
        values.append(
            (
                row["plaza_identifier"],
                row["plaza_name"],
                row["date"],
                row["hour"],
                row["vehicle_class"],
                round(revenue, 2),
                int(row["txn_count"]),
            )
        )

    insert_sql = sql.SQL(
        """
        INSERT INTO {table} (
            plaza_identifier, plaza_name, date, hour,
            vehicle_class, revenue, txn_count
        ) VALUES %s
        ON CONFLICT (plaza_identifier, date, hour, vehicle_class)
        DO UPDATE SET
            plaza_name = EXCLUDED.plaza_name,
            revenue = CASE
                WHEN EXCLUDED.revenue > {table}.revenue THEN EXCLUDED.revenue
                ELSE {table}.revenue
            END,
            txn_count = CASE
                WHEN EXCLUDED.revenue > {table}.revenue THEN EXCLUDED.txn_count
                ELSE {table}.txn_count
            END
        """
    ).format(table=sql.Identifier(REVENUE_DISTRIBUTION_PER_CLASS_TABLE))

    # Count existing keys for stats
    keys = [
        (row["plaza_identifier"], row["date"], row["hour"], row["vehicle_class"])
        for row in rows
    ]
    with conn.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                """
                SELECT plaza_identifier, date, hour, vehicle_class
                FROM {table}
                WHERE (plaza_identifier, date, hour, vehicle_class) IN %s
                """
            ).format(table=sql.Identifier(REVENUE_DISTRIBUTION_PER_CLASS_TABLE)),
            (tuple(keys),),
        )
        existing = {tuple(r) for r in cursor.fetchall()}
        execute_values(cursor, insert_sql.as_string(conn), values)
    conn.commit()

    updated = sum(1 for k in keys if k in existing)
    inserted = len(keys) - updated
    return inserted, updated


def process_etc_file(path: Path) -> list[dict]:
    print(f"  Reading: {path.name}")
    df = read_excel_file(path, required_fields=ETC_REQUIRED_FIELDS)
    if df.empty:
        print("  Empty file — skip.")
        return []

    dt_col = find_column_by_aliases(df, ETC_DATETIME_COLUMN_ALIASES)
    datetime_format = detect_datetime_format(df[dt_col].tolist())
    validate_etc_dataframe(df, path.name, datetime_format)
    prepared = prepare_etc_dataframe(df, datetime_format)
    rows = aggregate_hourly_revenue(prepared)
    print(f"  Prepared {len(rows)} hourly class revenue row(s)")
    return rows


def run() -> None:
    require_plaza_settings()
    load_all_env()
    start, end = validate_interval(FROM_DATE, TO_DATE)
    download_folder = Path(DOWNLOAD_FOLDER)
    download_folder.mkdir(parents=True, exist_ok=True)

    print("Module 4 — ETC revenue by vehicle class (hourly)")
    print(f"Plaza: {PLAZA_NAME} ({PLAZA_IDENTIFIER})")
    print(f"Entity: {ENTITY_NAME}")
    print(f"Date range: {start.isoformat()} → {end.isoformat()}")
    print(f"Download folder: {download_folder.resolve()}")
    print(f"Dry run: {DRY_RUN}\n")

    with psycopg2.connect(**submissions_db_kwargs()) as submissions_conn:
        records = fetch_etc_records(
            submissions_conn,
            entity_name=ENTITY_NAME,
            start=start,
            end=end,
        )

    print(f"Records with etc_file_url: {len(records)}\n")
    if not records:
        print("No ETC files found for the given filters.")
        return

    analytics_conn = None
    if not DRY_RUN:
        analytics_conn = psycopg2.connect(**get_analytics_db_connection_kwargs())
        ensure_revenue_distribution_per_class_table(
            analytics_conn, REVENUE_DISTRIBUTION_PER_CLASS_TABLE
        )

    acc: dict[tuple, dict] = {}
    stats = {
        "found": len(records),
        "downloaded": 0,
        "skipped": 0,
        "failed": 0,
        "processed": 0,
        "read_errors": 0,
        "inserted": 0,
        "updated": 0,
    }

    try:
        for index, record in enumerate(records, start=1):
            record_id = record["id"]
            url = str(record["etc_file_url"]).strip()
            filename = filename_from_url(url, record_id)
            local_path = build_local_path(
                download_folder,
                record["entity_name"],
                record["date"],
                record.get("shift"),
                filename,
            )
            prefix = (
                f"[{index}/{len(records)}] id={record_id} "
                f"date={record['date']} shift={record.get('shift')}"
            )

            if (
                SKIP_EXISTING
                and local_path.is_file()
                and local_path.stat().st_size > 0
            ):
                print(f"{prefix} SKIP download (exists): {local_path}")
                stats["skipped"] += 1
            else:
                try:
                    print(f"{prefix} DOWNLOAD → {local_path}")
                    download_file(url, local_path)
                    stats["downloaded"] += 1
                except requests.RequestException as exc:
                    print(f"{prefix} DOWNLOAD FAILED: {exc}")
                    stats["failed"] += 1
                    continue

            if local_path.suffix.lower() not in EXCEL_EXTENSIONS:
                print(f"{prefix} SKIP (unsupported type): {local_path.suffix}")
                continue

            try:
                file_rows = process_etc_file(local_path)
            except UnmappedValueError:
                raise
            except Exception as exc:
                if is_skippable_excel_read_error(exc):
                    print(f"{prefix} READ SKIP: {exc}")
                    stats["read_errors"] += 1
                    continue
                raise

            touched = merge_into_accumulator(acc, file_rows)
            stats["processed"] += 1

            if not touched:
                continue

            batch = []
            for key in touched:
                row = dict(acc[key])
                row["revenue"] = round(row["revenue"], 2)
                batch.append(row)

            if DRY_RUN:
                print(f"  DRY RUN upsert {len(batch)} cumulative key(s)")
                continue

            inserted, updated = upsert_revenue_if_greater(analytics_conn, batch)
            stats["inserted"] += inserted
            stats["updated"] += updated
            print(f"  DB upsert: inserted={inserted}, updated={updated}")

    finally:
        if analytics_conn is not None:
            analytics_conn.close()

    print("\nSummary")
    print(f"  Found:       {stats['found']}")
    print(f"  Downloaded:  {stats['downloaded']}")
    print(f"  Skip exists: {stats['skipped']}")
    print(f"  DL failed:   {stats['failed']}")
    print(f"  Processed:   {stats['processed']}")
    print(f"  Read errors: {stats['read_errors']}")
    if not DRY_RUN:
        print(f"  Inserted:    {stats['inserted']}")
        print(f"  Updated:     {stats['updated']}")
    print(f"  Unique keys in run: {len(acc)}")


def main() -> None:
    try:
        run()
    except (RuntimeError, ValueError, UnmappedValueError, psycopg2.Error) as exc:
        print(f"\nError: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
