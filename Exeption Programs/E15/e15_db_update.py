"""
E15 — aggregate Applicable Rate by Date & Time month into audit_exception_metrics.

Standalone usage (DB update only):
  1. Set DB_UPDATE_ONLY = True
  2. Set MERGED_OUTPUT_FILE below
  3. python e15_db_update.py
     Plaza id is taken from PLAZA_IDENTIFIER in E15.py.

Full pipeline:
  Called from E15.py after from_to_combined is written (when UPDATE_DB=True).

Rules:
  - Group by year/month of Date & Time
  - Exclude Applicable Rate that is empty, zero, or negative
  - total_count = number of included rows; total_amount = sum(Applicable Rate)
  - Insert if plaza+exception+year+month missing
  - If row exists, always overwrite total_count and total_amount
"""

from __future__ import annotations

import os
import re
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

# ISO date first — dayfirst=True on YYYY-MM-DD swaps month/day for days 1–12.
_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)?"
)


def parse_output_datetimes(values) -> pd.Series:
    series = pd.Series(values, dtype="object")
    text = series.map(
        lambda v: ""
        if v is None or (isinstance(v, float) and pd.isna(v))
        else str(v).strip()
    )
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    iso_mask = text.map(lambda s: bool(_ISO_DATETIME_RE.match(s)))
    if iso_mask.any():
        parsed.loc[iso_mask] = pd.to_datetime(
            text[iso_mask], errors="coerce", dayfirst=False
        )
    other = (~iso_mask) & text.ne("")
    if other.any():
        parsed.loc[other] = pd.to_datetime(
            text[other], errors="coerce", format="mixed", dayfirst=True
        )
    return parsed

# ---------------------------------------------------------------------------
DB_UPDATE_ONLY = False

MERGED_OUTPUT_FILE = (
    r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E15\output\from_to_combined.xlsx"
)


# E15 — Same vehicles get exempted while user fee is collected at subsequent plaza
EXCEPTION_TYPE_ID = 15

DRY_RUN = False
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR.parent / "E4" / ".env"
WEBSITE_ENV = BASE_DIR.parent.parent / "Website" / "backend" / ".env"

DATE_ALIASES = [
    "Date & Time",
    "DATE_TIME_FROM",
    "DATE_TIME_TO",
    "Date & Time_TO",
    "Tag Read Date Time",
    "read_datetime",
]
RATE_ALIASES = [
    "Applicable Rate",
    "applicable rate",
    "ApplicableRate",
]


def load_env() -> None:
    # Prefer process env (Docker); Website/backend/.env; E4/.env fills gaps.
    backend_root = os.environ.get("WEBSITE_BACKEND_ROOT", "").strip()
    if backend_root:
        backend_env = Path(backend_root).expanduser() / ".env"
        if backend_env.is_file():
            load_dotenv(backend_env, override=False)
    if WEBSITE_ENV.is_file():
        load_dotenv(WEBSITE_ENV, override=False)
    if ENV_FILE.is_file():
        load_dotenv(ENV_FILE, override=False)
    if (
        not WEBSITE_ENV.is_file()
        and not ENV_FILE.is_file()
        and not (
            os.getenv("DB_HOST", "").strip()
            and (
                os.getenv("Toll_Analytics_DB", "").strip()
                or os.getenv("DB_NAME", "").strip()
            )
        )
    ):
        raise FileNotFoundError(
            f"Env file not found: tried {WEBSITE_ENV} and {ENV_FILE}"
        )


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required env var: {name} "
            f"(checked process env, {WEBSITE_ENV}, {ENV_FILE})"
        )
    return value


def metrics_table_name() -> str:
    return (
        os.getenv("Exception_Metrics_Table", "").strip()
        or os.getenv("EXCEPTION_METRICS_TABLE", "").strip()
        or "audit_exception_metrics"
    )


def connection_kwargs() -> dict:
    database = (
        os.getenv("Toll_Analytics_DB", "").strip()
        or os.getenv("ANALYTICS_DB_NAME", "").strip()
        or os.getenv("DB_NAME", "").strip()
    )
    if not database:
        raise RuntimeError(
            "Missing analytics DB name "
            "(Toll_Analytics_DB / ANALYTICS_DB_NAME / DB_NAME)"
        )
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


def _to_float_or_none(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "")
    if text == "" or text.lower() in {"nan", "none", "nat"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def aggregate_monthly_applicable_rate(
    df: pd.DataFrame,
    *,
    date_aliases: list[str] | None = None,
    rate_aliases: list[str] | None = None,
    force_period: tuple[int, int] | None = None,
) -> list[dict]:
    """
    Group by year/month of Date & Time.
    Only rows with Applicable Rate > 0.
    total_amount = sum(Applicable Rate); total_count = row count.

    When force_period=(year, month) is set (pipeline batch), roll the whole
    run into that single month instead of splitting by Date & Time.
    """
    if df is None or df.empty:
        return []

    headers = [str(c) for c in df.columns]
    date_col = resolve_column(headers, date_aliases or DATE_ALIASES)
    rate_col = resolve_column(headers, rate_aliases or RATE_ALIASES)

    missing = []
    if not date_col and force_period is None:
        missing.append("Date & Time")
    if not rate_col:
        missing.append("Applicable Rate")
    if missing:
        raise KeyError(
            f"Combined file missing columns: {missing}. "
            f"Available: {list(df.columns)}"
        )

    work = df.copy()
    work["_rate"] = work[rate_col].map(_to_float_or_none)
    work = work.dropna(subset=["_rate"])
    work = work.loc[work["_rate"] > 0].copy()
    if work.empty:
        print("No rows with Applicable Rate > 0 for monthly aggregation.")
        return []

    if force_period is not None:
        year, month = int(force_period[0]), int(force_period[1])
        total_amount = Decimal(str(round(float(work["_rate"].sum()), 2)))
        total_count = int(len(work))
        print(
            f"Pipeline period {year}-{month:02d}: "
            f"count={total_count:,}, amount={total_amount:,.2f}"
        )
        return [
            {
                "year": year,
                "month": month,
                "total_count": total_count,
                "total_amount": total_amount,
            }
        ]

    work["_dt"] = parse_output_datetimes(work[date_col])
    work = work.dropna(subset=["_dt"])
    if work.empty:
        print("No rows with parseable Date & Time for monthly aggregation.")
        return []

    work["year"] = work["_dt"].dt.year.astype(int)
    work["month"] = work["_dt"].dt.month.astype(int)

    grouped = (
        work.groupby(["year", "month"], as_index=False)
        .agg(
            total_amount=("_rate", "sum"),
            total_count=("_rate", "size"),
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


def upsert_monthly_metrics(
    conn,
    *,
    plaza_identifier: str,
    exception_type_id: int,
    rows: list[dict],
    dry_run: bool = False,
    table_name: str | None = None,
) -> dict[str, int]:
    """Insert if missing; always overwrite when a row already exists."""
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
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
        """
    ).format(table=table_id)
    update_sql = sql.SQL(
        """
        UPDATE {table}
        SET total_amount = %s,
            total_count = %s,
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

    if not dry_run:
        conn.commit()
    return stats


def update_db_from_dataframe(
    df: pd.DataFrame,
    plaza_identifier: str,
    *,
    exception_type_id: int = EXCEPTION_TYPE_ID,
    dry_run: bool = False,
    date_aliases: list[str] | None = None,
    rate_aliases: list[str] | None = None,
    force_period: tuple[int, int] | None = None,
) -> dict[str, int]:
    plaza_identifier = str(plaza_identifier or "").strip()
    if not plaza_identifier:
        raise RuntimeError("plaza_identifier is required.")

    load_env()
    conn_kw = connection_kwargs()
    table = metrics_table_name()
    rows = aggregate_monthly_applicable_rate(
        df,
        date_aliases=date_aliases,
        rate_aliases=rate_aliases,
        force_period=force_period,
    )
    print(f"Target DB: {conn_kw['database']}.{table}")
    print(f"Plaza: {plaza_identifier}")
    print(f"exception_type_id: {exception_type_id}")
    print(f"Months to sync: {len(rows)}")
    for row in rows:
        print(
            f"  {row['year']}-{row['month']:02d}: "
            f"rows(total_count)={row['total_count']:,}, "
            f"rate(total_amount)={row['total_amount']:,.2f}"
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
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    else:
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
            "DB_UPDATE_ONLY is False. Set it True and fill MERGED_OUTPUT_FILE "
            "to run DB update alone.\n"
            "Plaza id is PLAZA_IDENTIFIER in E15.py.\n"
            "Or run: python E15.py for the full pipeline."
        )
        return 1

    if not str(MERGED_OUTPUT_FILE).strip():
        raise RuntimeError("Set MERGED_OUTPUT_FILE at the top of e15_db_update.py.")

    from E15 import PLAZA_IDENTIFIER

    if not str(PLAZA_IDENTIFIER).strip():
        raise RuntimeError("Set PLAZA_IDENTIFIER at the top of E15.py.")

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
