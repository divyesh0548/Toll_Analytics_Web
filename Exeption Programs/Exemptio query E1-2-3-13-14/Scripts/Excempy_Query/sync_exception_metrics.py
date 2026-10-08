"""
Sync annexure Summary sheet totals into toll_analytics.audit_exception_metrics.

Standalone usage:
  Set OUTPUT_FOLDER and PLAZA_IDENTIFIER below, then run:
  python sync_exception_metrics.py

Upsert rule:
  - Insert when no row exists for (plaza_identifier, exception_type_id, year, month)
  - Update total_amount + total_count only when the new count is greater than the existing count
  - Otherwise leave the existing row unchanged

Env (.env at repo root):
  RDS_HOST, RDS_PORT, RDS_USER, RDS_PASSWORD
  Toll_Analytics_DB=toll_analytics
  Exception_Metrics_Table=audit_exception_metrics
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
load_dotenv(REPO_ROOT / ".env")

_FINAL_SCRIPTS_DIR = SCRIPT_DIR / "Final_7_scripts"
if str(_FINAL_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_FINAL_SCRIPTS_DIR))

from annexure_plaza_config import resolve_plaza_identifier  # noqa: E402

# =============================================================================
# Standalone run — edit these before: python sync_exception_metrics.py
# =============================================================================
OUTPUT_FOLDER = r"C:\Divyesh\NHIT_File_process\Portal\File_Process\Exempt_Query\4_Full_Exempt_Pipeline\Odhaki_Full_Pipeline\output\annexure"
PLAZA_IDENTIFIER = r"d55c2122-117c-45be-8554-7ea76730932b"
# Optional fallback if PLAZA_IDENTIFIER is empty (uses annexure_plaza_config.json)
PLAZA_NAME = r"ODAKHI"

SUMMARY_SHEET_CANDIDATES = ("Summary", "Sumapry")
AMOUNT_COLUMN = "Total_Amount"
MONTH_COLUMN = "Month"
COUNT_COLUMNS = ("Transaction_Count", "Unique_Transaction_Count")

# exception_type_id → source workbook filenames (matched case-insensitively).
# Types 1 and 13 SUM every listed file that is present (by month) before upsert.
EXCEPTION_FILE_MAP: Dict[int, Tuple[str, ...]] = {
    1: ("LNC CT.xlsx", "LNC FT.xlsx"),
    2: ("NLNC.xlsx",),
    3: ("commercial.xlsx",),
    13: ("govt etc + exmpt.xlsx", "multiple cat others + exmpt.xlsx"),
    14: ("multipe class.xlsx",),  # filename spelling matches annexure output
}

_TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _analytics_db_name() -> str:
    return (
        os.environ.get("Toll_Analytics_DB")
        or os.environ.get("TOLL_ANALYTICS_DB")
        or "toll_analytics"
    ).strip()


def _metrics_table_name() -> str:
    name = (
        os.environ.get("Exception_Metrics_Table")
        or os.environ.get("EXCEPTION_METRICS_TABLE")
        or "audit_exception_metrics"
    ).strip()
    if not _TABLE_NAME_PATTERN.match(name):
        raise ValueError(f"Invalid Exception_Metrics_Table name: {name!r}")
    return name


def _db_engine():
    host = os.environ.get("RDS_HOST", "").strip()
    port = os.environ.get("RDS_PORT", "5432").strip() or "5432"
    user = os.environ.get("RDS_USER", "").strip()
    password = os.environ.get("RDS_PASSWORD", "").strip()
    db_name = _analytics_db_name()
    missing = [
        label
        for label, value in (
            ("RDS_HOST", host),
            ("RDS_USER", user),
            ("RDS_PASSWORD", password),
            ("Toll_Analytics_DB", db_name),
        )
        if not value
    ]
    if missing:
        raise EnvironmentError(
            "Missing required database configuration in .env: " + ", ".join(missing)
        )
    return create_engine(
        f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
    )


def parse_month_label(value) -> Optional[Tuple[int, int]]:
    """Parse 'Apr-26' / 'Apr-2026' → (month, year). Returns None for Total / invalid."""
    text_value = str(value or "").strip()
    if not text_value or text_value.casefold() == "total":
        return None
    for fmt in ("%b-%y", "%b-%Y"):
        parsed = pd.to_datetime(text_value, format=fmt, errors="coerce")
        if not pd.isna(parsed):
            return int(parsed.month), int(parsed.year)
    return None


def _find_file(folder: Path, filename: str) -> Optional[Path]:
    target = filename.casefold()
    for path in folder.iterdir():
        if path.is_file() and path.name.casefold() == target and not path.name.startswith("~$"):
            return path
    return None


def _read_summary_sheet(file_path: Path) -> pd.DataFrame:
    last_error = None
    for sheet_name in SUMMARY_SHEET_CANDIDATES:
        try:
            return pd.read_excel(file_path, sheet_name=sheet_name)
        except ValueError as exc:
            last_error = exc
            continue
    # Fallback: first sheet if named oddly
    try:
        return pd.read_excel(file_path, sheet_name=0)
    except Exception as exc:
        raise ValueError(
            f"Could not read Summary sheet from '{file_path.name}': {last_error or exc}"
        ) from exc


def _pick_count_column(columns: Iterable[str]) -> Optional[str]:
    present = {str(col): str(col) for col in columns}
    present_cf = {str(col).casefold(): str(col) for col in columns}
    for candidate in COUNT_COLUMNS:
        if candidate in present:
            return present[candidate]
        if candidate.casefold() in present_cf:
            return present_cf[candidate.casefold()]
    return None


def _pick_column(columns: Iterable[str], expected: str) -> Optional[str]:
    expected_cf = expected.casefold()
    for col in columns:
        if str(col).casefold() == expected_cf:
            return str(col)
    return None


def extract_monthly_metrics(file_path: Path) -> Dict[Tuple[int, int], Dict[str, float]]:
    """
    Returns {(month, year): {"amount": float, "count": int}} from a workbook Summary sheet.
    Ignores the Total row.
    """
    df = _read_summary_sheet(file_path)
    month_col = _pick_column(df.columns, MONTH_COLUMN)
    amount_col = _pick_column(df.columns, AMOUNT_COLUMN)
    count_col = _pick_count_column(df.columns)
    if not month_col or not amount_col or not count_col:
        raise ValueError(
            f"'{file_path.name}' Summary sheet is missing Month / Total_Amount / count columns."
        )

    metrics: Dict[Tuple[int, int], Dict[str, float]] = {}
    for _, row in df.iterrows():
        parsed = parse_month_label(row.get(month_col))
        if not parsed:
            continue
        month_num, year_num = parsed
        try:
            amount = float(pd.to_numeric(row.get(amount_col), errors="coerce") or 0)
            count = int(float(pd.to_numeric(row.get(count_col), errors="coerce") or 0))
        except (TypeError, ValueError):
            continue
        key = (month_num, year_num)
        if key not in metrics:
            metrics[key] = {"amount": 0.0, "count": 0}
        metrics[key]["amount"] += amount
        metrics[key]["count"] += count
    return metrics


def collect_exception_metrics(output_folder: Path) -> Dict[int, Dict[Tuple[int, int], Dict[str, float]]]:
    """
    Build metrics keyed by exception_type_id → (month, year) → amount/count.

    Multi-file types (1 = LNC CT+FT, 13 = govt etc + multiple cat others)
    sum amount and count per month across every file that is present.
    """
    folder = Path(output_folder).expanduser().resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f"Output folder not found: {folder}")

    collected: Dict[int, Dict[Tuple[int, int], Dict[str, float]]] = {}
    notes: List[str] = []

    for exception_type_id, filenames in EXCEPTION_FILE_MAP.items():
        type_metrics: Dict[Tuple[int, int], Dict[str, float]] = {}
        found_names: List[str] = []
        for filename in filenames:
            path = _find_file(folder, filename)
            if not path:
                notes.append(f"missing {filename} for exception_type_id={exception_type_id}")
                continue
            found_names.append(path.name)
            file_metrics = extract_monthly_metrics(path)
            for key, values in file_metrics.items():
                if key not in type_metrics:
                    type_metrics[key] = {"amount": 0.0, "count": 0}
                type_metrics[key]["amount"] += values["amount"]
                type_metrics[key]["count"] += int(values["count"])
        if found_names:
            collected[exception_type_id] = type_metrics
            if len(filenames) > 1:
                notes.append(
                    f"exception_type_id={exception_type_id} summed from: "
                    + ", ".join(found_names)
                )
        else:
            notes.append(
                f"skipped exception_type_id={exception_type_id} (no source files present)"
            )

    if notes:
        print("Metrics collect notes: " + "; ".join(notes))

    if not collected:
        detail = "; ".join(notes) if notes else "no annexure summary workbooks found"
        raise ValueError(f"No exception metrics could be extracted: {detail}")

    return collected


def upsert_exception_metrics(
    plaza_identifier: str,
    metrics_by_type: Dict[int, Dict[Tuple[int, int], Dict[str, float]]],
) -> Tuple[int, int, int]:
    """
    Returns (inserted, updated, skipped).
    Update only when new count > existing count (writes both count and amount).
    """
    plaza_identifier = str(plaza_identifier or "").strip()
    if not plaza_identifier:
        raise ValueError("plaza_identifier is required.")

    table = _metrics_table_name()
    engine = _db_engine()
    now = datetime.now(timezone.utc)
    inserted = updated = skipped = 0

    select_sql = text(
        f"""
        SELECT id, total_count, total_amount
        FROM {table}
        WHERE plaza_identifier = :plaza_identifier
          AND exception_type_id = :exception_type_id
          AND year = :year
          AND month = :month
        ORDER BY id
        LIMIT 1
        """
    )
    insert_sql = text(
        f"""
        INSERT INTO {table} (
            plaza_identifier, exception_type_id, year, month,
            total_amount, total_count, severity, status, notes,
            created_at, updated_at
        ) VALUES (
            :plaza_identifier, :exception_type_id, :year, :month,
            :total_amount, :total_count, NULL, NULL, NULL,
            :created_at, :updated_at
        )
        """
    )
    update_sql = text(
        f"""
        UPDATE {table}
        SET total_amount = :total_amount,
            total_count = :total_count,
            updated_at = :updated_at
        WHERE id = :id
        """
    )

    with engine.begin() as conn:
        for exception_type_id, month_map in sorted(metrics_by_type.items()):
            for (month_num, year_num), values in sorted(month_map.items()):
                new_amount = round(float(values["amount"]), 2)
                new_count = int(values["count"])
                existing = conn.execute(
                    select_sql,
                    {
                        "plaza_identifier": plaza_identifier,
                        "exception_type_id": int(exception_type_id),
                        "year": int(year_num),
                        "month": int(month_num),
                    },
                ).mappings().first()

                if not existing:
                    conn.execute(
                        insert_sql,
                        {
                            "plaza_identifier": plaza_identifier,
                            "exception_type_id": int(exception_type_id),
                            "year": int(year_num),
                            "month": int(month_num),
                            "total_amount": new_amount,
                            "total_count": new_count,
                            "created_at": now,
                            "updated_at": now,
                        },
                    )
                    inserted += 1
                    continue

                existing_count = int(existing["total_count"] or 0)
                if new_count > existing_count:
                    conn.execute(
                        update_sql,
                        {
                            "id": existing["id"],
                            "total_amount": new_amount,
                            "total_count": new_count,
                            "updated_at": now,
                        },
                    )
                    updated += 1
                else:
                    skipped += 1

    return inserted, updated, skipped


def sync_exception_metrics_from_folder(
    output_folder: str | Path,
    plaza_identifier: str = "",
    plaza_name: str = "",
) -> Tuple[bool, str]:
    """
    Public entry used by the Full Exempt Pipeline and CLI.
    Provide plaza_identifier directly, or plaza_name to resolve from config.
    """
    try:
        identifier = str(plaza_identifier or "").strip()
        if not identifier:
            identifier = resolve_plaza_identifier(plaza_name) or ""
        if not identifier:
            return (
                False,
                "plaza_identifier is required. Set PLAZA_IDENTIFIER (or PLAZA_NAME with a "
                "mapping in annexure_plaza_config.json → plaza_identifiers).",
            )

        folder = Path(output_folder)
        metrics = collect_exception_metrics(folder)
        inserted, updated, skipped = upsert_exception_metrics(identifier, metrics)
        month_rows = sum(len(v) for v in metrics.values())
        return (
            True,
            (
                f"Exception metrics synced for plaza_identifier '{identifier}': "
                f"{month_rows} month-row(s) across {len(metrics)} exception type(s); "
                f"inserted={inserted}, updated={updated}, skipped={skipped}."
            ),
        )
    except Exception as exc:
        return False, f"Exception metrics DB update failed: {exc}"


def main() -> int:
    output_folder = str(OUTPUT_FOLDER or "").strip()
    plaza_identifier = str(PLAZA_IDENTIFIER or "").strip()
    plaza_name = str(PLAZA_NAME or "").strip()

    if not output_folder:
        print("Set OUTPUT_FOLDER at the top of sync_exception_metrics.py before running.")
        return 1

    ok, message = sync_exception_metrics_from_folder(
        output_folder,
        plaza_identifier=plaza_identifier,
        plaza_name=plaza_name,
    )
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
