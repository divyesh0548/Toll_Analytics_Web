"""
E5 Invalid lookup — aggregate Impact by month into audit_exception_metrics.

Rules:
  - Sheet "Upto Lcv": all rows, group by Reader Read Time month/year,
    total_count = row count, total_amount = sum(Impact)
  - Sheet "2-axel and above": only Matched = yes (case-insensitive),
    same date/Impact aggregation
  - Combine both sheets per year+month, then upsert exception_type_id = 5
  - Existing month is updated when new count OR new amount is greater

Standalone (DB update only):
  1. Set DB_UPDATE_ONLY = True
  2. Set OUTPUT_FILE and PLAZA_IDENTIFIER below
  3. python invalid_lookup_db_update.py

Full pipeline:
  Called from Invalid_lookup_query.py after the workbook is written.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg2

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from e5_db_update import (  # noqa: E402
    connection_kwargs,
    fetch_plaza,
    load_env,
    upsert_monthly_metrics,
)

# ---------------------------------------------------------------------------
# Standalone controls — edit these to run DB update only
# ---------------------------------------------------------------------------
DB_UPDATE_ONLY = True

OUTPUT_FILE = (
    r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E5\output"
    r"\Bassi IHMCL - Current output.xlsx"
)

PLAZA_IDENTIFIER = "94ecdec1-550c-4b4c-a94d-1df3b5fb4ac6"
EXCEPTION_TYPE_ID = 5
DRY_RUN = False
# ---------------------------------------------------------------------------

SHEET_UPTO_LCV = "Upto Lcv"
SHEET_TWO_AXLE = "2-axel and above"
DATE_COL = "Reader Read Time"
IMPACT_COL = "Impact"
MATCHED_COL = "Matched"
MATCHED_YES = {"yes", "y", "true", "1"}

DATE_ALIASES = [
    "Reader Read Time",
    "Date & Time",
    "Tag Read Date Time",
    "Settlement Date",
]
IMPACT_ALIASES = ["Impact", "Exception Value", "potential_exception_value"]


def _resolve_col(df: pd.DataFrame, preferred: str, aliases: list[str]) -> str:
    lookup = {str(c).strip().casefold(): str(c).strip() for c in df.columns}
    for name in [preferred, *aliases]:
        hit = lookup.get(str(name).strip().casefold())
        if hit is not None:
            return hit
    raise KeyError(
        f"Column not found. Tried {[preferred, *aliases]}. Available: {list(df.columns)}"
    )


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).replace("\n", " ").strip() for c in out.columns]
    return out


def _aggregate_sheet(
    df: pd.DataFrame,
    *,
    sheet_label: str,
    matched_only: bool = False,
) -> list[dict]:
    if df is None or df.empty:
        print(f"  [{sheet_label}] empty — 0 months")
        return []

    work = _normalize_columns(df)
    date_col = _resolve_col(work, DATE_COL, DATE_ALIASES)
    impact_col = _resolve_col(work, IMPACT_COL, IMPACT_ALIASES)

    if matched_only:
        if MATCHED_COL not in work.columns:
            print(
                f"  [{sheet_label}] no {MATCHED_COL!r} column — "
                "0 rows after Matched=yes filter"
            )
            return []
        matched = work[MATCHED_COL].astype(str).str.strip().str.casefold()
        work = work.loc[matched.isin(MATCHED_YES)].copy()
        print(f"  [{sheet_label}] Matched=yes rows: {len(work):,}")
    else:
        print(f"  [{sheet_label}] rows: {len(work):,}")

    if work.empty:
        return []

    work["_ts"] = pd.to_datetime(work[date_col], errors="coerce")
    work["_impact"] = pd.to_numeric(work[impact_col], errors="coerce").fillna(0)
    work = work.dropna(subset=["_ts"]).copy()
    if work.empty:
        print(f"  [{sheet_label}] no parseable {date_col!r} values")
        return []

    work["year"] = work["_ts"].dt.year.astype(int)
    work["month"] = work["_ts"].dt.month.astype(int)

    grouped = (
        work.groupby(["year", "month"], as_index=False)
        .agg(total_count=("_impact", "size"), total_amount=("_impact", "sum"))
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
        print(
            f"  [{sheet_label}] {row.year}-{int(row.month):02d}: "
            f"count={int(row.total_count):,}, amount={Decimal(str(row.total_amount)):,.2f}"
        )
    return rows


def _merge_monthly(parts: list[list[dict]]) -> list[dict]:
    bucket: dict[tuple[int, int], dict] = {}
    for rows in parts:
        for row in rows:
            key = (int(row["year"]), int(row["month"]))
            cur = bucket.get(key)
            if cur is None:
                bucket[key] = {
                    "year": key[0],
                    "month": key[1],
                    "total_count": int(row["total_count"]),
                    "total_amount": Decimal(str(row["total_amount"])),
                }
            else:
                cur["total_count"] = int(cur["total_count"]) + int(row["total_count"])
                cur["total_amount"] = Decimal(str(cur["total_amount"])) + Decimal(
                    str(row["total_amount"])
                )
    return [bucket[k] for k in sorted(bucket)]


def aggregate_invalid_lookup_workbook(
    workbook: str | Path | dict[str, pd.DataFrame],
) -> list[dict]:
    """
    Build monthly totals from an Invalid-lookup workbook (path or sheet dict).
    Combines Upto Lcv (all) + 2-axel and above (Matched=yes).
    """
    if isinstance(workbook, dict):
        sheets = {
            str(k): _normalize_columns(v) if v is not None else pd.DataFrame()
            for k, v in workbook.items()
        }
        source = "in-memory sheets"
    else:
        path = Path(workbook)
        if not path.is_file():
            raise FileNotFoundError(f"Output workbook not found: {path}")
        xl = pd.ExcelFile(path)
        name_lookup = {str(n).strip().casefold(): n for n in xl.sheet_names}
        sheets = {}
        for wanted in (SHEET_UPTO_LCV, SHEET_TWO_AXLE):
            hit = name_lookup.get(wanted.casefold())
            if hit is None:
                print(f"WARNING: sheet {wanted!r} missing — treating as empty")
                sheets[wanted] = pd.DataFrame()
            else:
                sheets[wanted] = _normalize_columns(
                    pd.read_excel(path, sheet_name=hit, dtype=object)
                )
        source = str(path)

    print(f"Aggregating Impact by month from: {source}")
    upto_rows = _aggregate_sheet(
        sheets.get(SHEET_UPTO_LCV, pd.DataFrame()),
        sheet_label=SHEET_UPTO_LCV,
        matched_only=False,
    )
    above_rows = _aggregate_sheet(
        sheets.get(SHEET_TWO_AXLE, pd.DataFrame()),
        sheet_label=SHEET_TWO_AXLE,
        matched_only=True,
    )
    combined = _merge_monthly([upto_rows, above_rows])
    print(f"Combined months: {len(combined)}")
    for row in combined:
        print(
            f"  TOTAL {row['year']}-{row['month']:02d}: "
            f"count={row['total_count']:,}, amount={row['total_amount']:,.2f}"
        )
    return combined


def update_db_from_invalid_lookup_file(
    output_file: str | Path,
    plaza_identifier: str,
    *,
    exception_type_id: int = EXCEPTION_TYPE_ID,
    dry_run: bool = False,
) -> dict[str, int]:
    """Read Invalid-lookup Excel, aggregate Impact by month, upsert metrics."""
    plaza_identifier = str(plaza_identifier or "").strip()
    if not plaza_identifier:
        raise RuntimeError("plaza_identifier is required.")

    rows = aggregate_invalid_lookup_workbook(output_file)
    return _upsert(rows, plaza_identifier, exception_type_id, dry_run)


def update_db_from_invalid_lookup_sheets(
    upto_df: pd.DataFrame,
    above_df: pd.DataFrame,
    plaza_identifier: str,
    *,
    exception_type_id: int = EXCEPTION_TYPE_ID,
    dry_run: bool = False,
) -> dict[str, int]:
    """Same upsert as file path, but from in-memory sheet DataFrames."""
    plaza_identifier = str(plaza_identifier or "").strip()
    if not plaza_identifier:
        raise RuntimeError("plaza_identifier is required.")

    rows = aggregate_invalid_lookup_workbook(
        {SHEET_UPTO_LCV: upto_df, SHEET_TWO_AXLE: above_df}
    )
    return _upsert(rows, plaza_identifier, exception_type_id, dry_run)


def upsert_invalid_lookup_monthly(
    rows: list[dict],
    plaza_identifier: str,
    *,
    exception_type_id: int = EXCEPTION_TYPE_ID,
    dry_run: bool = False,
) -> dict[str, int]:
    """Upsert pre-aggregated monthly Impact rows into audit_exception_metrics."""
    load_env()
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


def _upsert(
    rows: list[dict],
    plaza_identifier: str,
    exception_type_id: int,
    dry_run: bool,
) -> dict[str, int]:
    return upsert_invalid_lookup_monthly(
        rows,
        plaza_identifier,
        exception_type_id=exception_type_id,
        dry_run=dry_run,
    )


def main() -> int:
    if not DB_UPDATE_ONLY:
        print(
            "DB_UPDATE_ONLY is False. Set it True and fill OUTPUT_FILE / "
            "PLAZA_IDENTIFIER to run DB update alone.\n"
            "Or run: python Invalid_lookup_query.py for the full pipeline."
        )
        return 1

    if not str(OUTPUT_FILE).strip():
        raise RuntimeError("Set OUTPUT_FILE at the top of invalid_lookup_db_update.py.")
    if not str(PLAZA_IDENTIFIER).strip():
        raise RuntimeError(
            "Set PLAZA_IDENTIFIER at the top of invalid_lookup_db_update.py."
        )

    update_db_from_invalid_lookup_file(
        OUTPUT_FILE,
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
