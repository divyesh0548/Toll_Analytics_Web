"""
E11 — AVC class consistency by vehicle (Raksha-style accuracy workbook).

1. Download VRN files for ENTITY_NAME between FROM_DATE and TO_DATE.
2. Combine rows by the Date column's calendar month.
3. Normalize AVC with Plaza_db_update/config/vehicle_class.json.
   A label that is not in that file is counted as Undefined.
4. For each vehicle, the highest AVC count is the correct count.
   A tie uses that count once. It is not added twice.
   If Undefined is strictly the highest, the next defined class count is used.
5. The month result is right counts / all rows in that month.
   Vehicle percentages are not added together.
6. Output is an Excel workbook (one sheet per month) with per-vehicle class
   counts — same style as AVC-accuracy-Raksha.xlsx. That file is uploaded.

Run:
  1. In e11_config.json, set date_format for the entity to dd/mm/yyyy or mm/dd/yyyy
  2. Set ENTITY_NAME, FROM_DATE, TO_DATE, and PLAZA_IDENTIFIER below
  3. python Main_E11.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BASE_DIR.parent))
from common.s3_output_upload import (  # noqa: E402
    month_label_from_periods,
    upload_exception_output,
)

REPO_ROOT = BASE_DIR.parent.parent
WEBSITE_ENV = REPO_ROOT / "Website" / "backend" / ".env"
E4_VRN_PATH = BASE_DIR.parent / "E4" / "vrn-download-merge.py"
PLAZA_DIR = REPO_ROOT / "Plaza_db_update"
CONFIG_PATH = BASE_DIR / "e11_config.json"
VEHICLE_CLASS_PATH = PLAZA_DIR / "config" / "vehicle_class.json"

# --- Runtime inputs (Website overrides via E11_* env) ---
ENTITY_NAME = "bassi"
FROM_DATE = "2026-01-01"
TO_DATE = "2026-02-28"
# Analytics plaza id. Exception type 11 stores only the monthly right-class percentage.
PLAZA_IDENTIFIER = "94ecdec1-550c-4b4c-a94d-1df3b5fb4ac6"
EXCEPTION_TYPE_ID = 11

DOWNLOAD_FOLDER = BASE_DIR / "vrn_downloads"
OUTPUT_DIR = BASE_DIR / "output"
# When set (Website job), use local VRN files instead of submissions download.
VRN_INPUT_FOLDER = ""
Metrics_DB_Update = True
DB_DRY_RUN = False
UPLOAD_OUTPUT_TO_S3 = True
# Pipeline batch period (optional). When set, metrics + S3 label use this month.
PERIOD_YEAR: int | None = None
PERIOD_MONTH: int | None = None
EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".csv"}
_MONTH_ABBR = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

# ISO year-first stamps (Excel exports / merged files). Must win over dayfirst
# so 2026-08-01 is 1 Aug, not 8 Jan.
_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)?(?:\s*[AaPp][Mm])?$"
)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def apply_website_env_overrides() -> None:
    global ENTITY_NAME, FROM_DATE, TO_DATE, PLAZA_IDENTIFIER
    global VRN_INPUT_FOLDER, OUTPUT_DIR, DOWNLOAD_FOLDER
    global Metrics_DB_Update, DB_DRY_RUN, UPLOAD_OUTPUT_TO_S3
    global PERIOD_YEAR, PERIOD_MONTH

    if os.environ.get("E11_ENTITY_NAME", "").strip():
        ENTITY_NAME = os.environ["E11_ENTITY_NAME"].strip()
    if os.environ.get("E11_FROM_DATE", "").strip():
        FROM_DATE = os.environ["E11_FROM_DATE"].strip()
    if os.environ.get("E11_TO_DATE", "").strip():
        TO_DATE = os.environ["E11_TO_DATE"].strip()
    if os.environ.get("E11_PLAZA_IDENTIFIER", "").strip():
        PLAZA_IDENTIFIER = os.environ["E11_PLAZA_IDENTIFIER"].strip()
    if os.environ.get("E11_VRN_INPUT_FOLDER", "").strip():
        VRN_INPUT_FOLDER = os.environ["E11_VRN_INPUT_FOLDER"].strip()
    if os.environ.get("E11_OUTPUT_DIR", "").strip():
        OUTPUT_DIR = Path(os.environ["E11_OUTPUT_DIR"].strip())
    if "E11_METRICS_DB_UPDATE" in os.environ:
        Metrics_DB_Update = _env_flag("E11_METRICS_DB_UPDATE", Metrics_DB_Update)
    if "E11_UPLOAD_OUTPUT_TO_S3" in os.environ:
        UPLOAD_OUTPUT_TO_S3 = _env_flag("E11_UPLOAD_OUTPUT_TO_S3", UPLOAD_OUTPUT_TO_S3)
    if "E11_DB_DRY_RUN" in os.environ:
        DB_DRY_RUN = _env_flag("E11_DB_DRY_RUN", DB_DRY_RUN)

    year_raw = os.environ.get("E11_PERIOD_YEAR", "").strip()
    month_raw = os.environ.get("E11_PERIOD_MONTH", "").strip()
    if year_raw and month_raw:
        year = int(year_raw)
        month = int(month_raw)
        if not (1990 <= year <= 2100 and 1 <= month <= 12):
            raise RuntimeError(
                f"Invalid E11_PERIOD_YEAR/MONTH: {year_raw!r}/{month_raw!r}"
            )
        PERIOD_YEAR = year
        PERIOD_MONTH = month


def _metrics_table_name() -> str:
    name = (
        os.getenv("Exception_Metrics_Table", "").strip()
        or os.getenv("EXCEPTION_METRICS_TABLE", "").strip()
        or "audit_exception_metrics"
    )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise RuntimeError(f"Invalid Exception_Metrics_Table: {name!r}")
    return name


def list_vrn_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise FileNotFoundError(f"VRN folder not found: {folder}")
    files = sorted(
        p
        for p in folder.iterdir()
        if p.is_file()
        and p.suffix.lower() in EXCEL_EXTENSIONS
        and not p.name.startswith("~$")
    )
    if not files:
        raise FileNotFoundError(f"No VRN Excel/CSV files under: {folder}")
    return files

_DAY_FIRST_FORMATS = (
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y %I:%M:%S %p",
    "%d/%m/%Y %I:%M %p",
    "%d-%m-%Y %I:%M:%S %p",
    "%d-%m-%Y %I:%M %p",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y",
    "%d/%m/%Y",
)
_MONTH_FIRST_FORMATS = (
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
    "%m-%d-%Y %I:%M:%S %p",
    "%m-%d-%Y %I:%M %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m-%d-%Y %H:%M:%S",
    "%m-%d-%Y %H:%M",
    "%m/%d/%Y",
    "%m-%d-%Y",
)
_PLAIN_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d-%b-%Y %H:%M:%S",
    "%d-%b-%Y",
)
_DATE_ORDERS = {"dd/mm/yyyy", "mm/dd/yyyy"}
_BLANK = {"", "na", "n/a", "null", "none", "nat", "nan", "-"}
UNDEFINED = "Undefined"


def _load_module(path: Path, name: str):
    if not path.is_file():
        raise FileNotFoundError(f"Module file not found: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(f"Config not found: {CONFIG_PATH}")
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        config = json.load(handle)
    from common.mapping_store import overlay_shared_config

    return overlay_shared_config(config, match_source="e11")


def canonical_classes() -> list[str]:
    from common.mapping_store import canonical_keys

    return canonical_keys("vehicle_class")


def _header_cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return " ".join(text.split())


def _header_key(value) -> str:
    from common.header_match import normalize_header_match

    return normalize_header_match(value)


def resolve_column(headers: list[str], aliases: list[str]) -> str | None:
    by_key = {
        key: header
        for header in headers
        if (key := _header_key(header))
    }
    for alias in aliases:
        key = _header_key(alias)
        match = by_key.get(key) if key else None
        if match:
            return match
    return None


class SkipFile(Exception):
    """User chose to skip a file whose column or keyword was not detected."""


def _unique_words(words: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for word in words:
        text = str(word).strip()
        key = _header_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(text)
    return ordered


def words_not_in_cells(words: list[str], cells: set[str]) -> list[str]:
    return [word for word in _unique_words(words) if _header_key(word) not in cells]


def prompt_skip_or_stop(path: Path, missing_words: list[str]) -> None:
    """Ask to skip this file or stop. Skip raises SkipFile."""
    print(f"\n  Not detected in {path.name}:")
    for word in missing_words:
        print(f"    {word}")
    # Website / Docker jobs: auto-skip bad files (no interactive stdin).
    if _env_flag("E11_NONINTERACTIVE", False) or not sys.stdin.isatty():
        print("  Non-interactive — skipping this file.")
        raise SkipFile(path.name)
    while True:
        try:
            choice = input("  Skip this file [s] or stop the program [x]? ").strip().lower()
        except EOFError:
            raise RuntimeError("No input — program stopped.") from None
        if choice in {"s", "skip"}:
            raise SkipFile(path.name)
        if choice in {"x", "stop"}:
            raise RuntimeError("Stopped by user.")
        print("  Type s to skip this file, or x to stop the program.")


def detect_header_row(df_raw: pd.DataFrame, keywords: list[str], scan_rows: int, min_matches: int) -> int:
    keyword_list = _unique_words(keywords)
    keyword_keys = {_header_key(keyword) for keyword in keyword_list}
    limit = min(int(scan_rows), len(df_raw))
    best_idx = None
    best_score = -1
    best_cells: set[str] = set()
    for row_idx in range(limit):
        cells = {_header_key(value) for value in df_raw.iloc[row_idx].tolist()}
        cells.discard("")
        score = sum(1 for key in keyword_keys if key in cells)
        if score > best_score:
            best_score = score
            best_idx = row_idx
            best_cells = cells
    if best_idx is None or best_score < int(min_matches):
        missing = words_not_in_cells(keyword_list, best_cells)
        raise LookupError(", ".join(missing) if missing else "header keywords")
    return best_idx


def date_order_for(entity_name: str, config: dict) -> str:
    """dd/mm/yyyy or mm/dd/yyyy from the entities list. Blank is not a guess."""
    key = str(entity_name or "").strip().casefold()
    for row in config.get("entities") or []:
        name = str(row.get("entity_name") or "").strip().casefold()
        if name != key:
            continue
        order = str(row.get("date_format") or "").strip().casefold()
        if order not in _DATE_ORDERS:
            raise RuntimeError(
                f"Set date_format for {entity_name!r} in e11_config.json "
                "to dd/mm/yyyy or mm/dd/yyyy."
            )
        return order
    raise RuntimeError(
        f"Add {entity_name!r} to the entities list in e11_config.json "
        "and set date_format to dd/mm/yyyy or mm/dd/yyyy."
    )


def parse_date(value, date_order: str) -> datetime | None:
    """
    Parse a VRN date cell.

    ISO YYYY-MM-DD is always year-first (never dayfirst), matching E10/E15.
    Otherwise use the plaza date_format from e11_config.json
    (dd/mm/yyyy vs mm/dd/yyyy).
    """
    text = _header_cell(value)
    if text.casefold() in _BLANK:
        return None

    # Strip a trailing time if Date and Time were concatenated oddly.
    # Keep strptime candidates that include time as well.
    if _ISO_DATETIME_RE.match(text) or text[:10].count("-") == 2 and text[:4].isdigit():
        iso_formats = (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %I:%M:%S %p",
            "%Y-%m-%d %I:%M %p",
            "%Y-%m-%d",
        )
        for fmt in iso_formats:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        parsed = pd.to_datetime(text, dayfirst=False, errors="coerce")
        if not pd.isna(parsed):
            return parsed.to_pydatetime()

    if date_order == "mm/dd/yyyy":
        formats = _MONTH_FIRST_FORMATS + _PLAIN_FORMATS
        dayfirst = False
    else:
        formats = _DAY_FIRST_FORMATS + _PLAIN_FORMATS
        dayfirst = True
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    parsed = pd.to_datetime(text, dayfirst=dayfirst, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def vehicle_key(value) -> str:
    return _header_cell(value).upper()


def read_vrn_file(path: Path, config: dict) -> pd.DataFrame:
    print(f"Reading: {path.name}")
    if path.suffix.lower() == ".csv":
        raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    else:
        raw = pd.read_excel(path, sheet_name=0, header=None, dtype=str)
    if raw.empty:
        raise ValueError(f"File is empty: {path.name}")
    keywords = config.get("header_keywords") or []
    try:
        header_idx = detect_header_row(
            raw,
            keywords,
            int(config.get("header_scan_rows") or 25),
            int(config.get("min_header_matches") or 2),
        )
    except LookupError as exc:
        prompt_skip_or_stop(path, [part.strip() for part in str(exc).split(",") if part.strip()])
        raise
    headers = [_header_cell(value) for value in raw.iloc[header_idx].tolist()]
    while headers and headers[-1] == "":
        headers.pop()
    body = raw.iloc[header_idx + 1 :, : len(headers)].copy()
    body.columns = headers
    body = body.dropna(how="all").reset_index(drop=True)

    header_cells = {_header_key(header) for header in headers}
    columns = config["columns"]
    found = {
        role: resolve_column(headers, aliases)
        for role, aliases in columns.items()
    }
    missing_words: list[str] = []
    for role, column in found.items():
        if column is None:
            missing_words.extend(words_not_in_cells(columns[role], header_cells))
    if missing_words:
        prompt_skip_or_stop(path, missing_words)
    print(
        f"  Header at row {header_idx + 1}: "
        f"vehicle={found['vehicle']!r}, date={found['date']!r}, avc={found['avc']!r}"
    )
    return pd.DataFrame(
        {
            "vehicle": body[found["vehicle"]].map(_header_cell),
            "date": body[found["date"]].map(_header_cell),
            "avc": body[found["avc"]].map(_header_cell),
        }
    )


def right_count(counts: Counter, class_names: list[str]) -> int:
    """Highest defined AVC count, once. Undefined wins only by giving way to the next class."""
    defined_counts = [int(counts.get(name, 0)) for name in class_names]
    best_defined = max(defined_counts) if defined_counts else 0
    undefined = int(counts.get(UNDEFINED, 0))
    if undefined > best_defined:
        return best_defined
    return best_defined


def month_frames(paths: list[Path], config: dict, date_order: str):
    sys.path.insert(0, str(PLAZA_DIR))
    from excel_common import is_excluded_vehicle_class, try_normalize_vehicle_class

    class_names = canonical_classes()
    buckets: dict[str, list[dict]] = defaultdict(list)
    undefined_labels: set[str] = set()
    skipped_date = 0
    skipped_vehicle = 0
    skipped_excluded = 0

    for path in paths:
        try:
            frame = read_vrn_file(path, config)
        except SkipFile:
            print(f"SKIP FILE: {path.name}")
            continue
        except (zipfile.BadZipFile, OSError, ValueError) as exc:
            message = str(exc).lower()
            if isinstance(exc, zipfile.BadZipFile) or "bad magic number" in message or "not a zip file" in message:
                print(f"SKIP corrupt file {path.name}: {exc}")
                continue
            raise
        programs = Path(__file__).resolve().parents[1]
        if str(programs) not in sys.path:
            sys.path.insert(0, str(programs))
        from common.date_order import infer_day_first

        file_order = date_order
        if "date" in frame.columns:
            detected = infer_day_first(frame["date"].tolist())
            if detected is True:
                file_order = "dd/mm/yyyy"
            elif detected is False:
                file_order = "mm/dd/yyyy"
        for record in frame.itertuples(index=False):
            vehicle = vehicle_key(record.vehicle)
            if not vehicle:
                skipped_vehicle += 1
                continue
            when = parse_date(record.date, file_order)
            if when is None:
                skipped_date += 1
                continue
            raw_avc = _header_cell(record.avc)
            if raw_avc and is_excluded_vehicle_class(raw_avc):
                skipped_excluded += 1
                continue
            canonical = try_normalize_vehicle_class(raw_avc) if raw_avc else None
            if canonical is None:
                if raw_avc:
                    undefined_labels.add(raw_avc)
                label = UNDEFINED
            else:
                label = canonical
            buckets[f"{when.year:04d}-{when.month:02d}"].append(
                {"vehicle": vehicle, "avc": label}
            )

    print(f"Rows skipped — no vehicle: {skipped_vehicle}, no date: {skipped_date}, excluded class: {skipped_excluded}")
    months = {
        key: pd.DataFrame(rows) if rows else pd.DataFrame(columns=["vehicle", "avc"])
        for key, rows in buckets.items()
    }
    return months, undefined_labels, class_names


def build_month_pivot(month_df: pd.DataFrame, class_names: list[str]) -> tuple[pd.DataFrame, dict]:
    grouped: dict[str, Counter] = defaultdict(Counter)
    for record in month_df.itertuples(index=False):
        grouped[record.vehicle][record.avc] += 1

    rows = []
    right_total = 0
    row_total = 0
    for vehicle in sorted(grouped):
        counts = grouped[vehicle]
        total = int(sum(counts.values()))
        correct = right_count(counts, class_names)
        right_total += correct
        row_total += total
        row = {"VEH REG NO": vehicle}
        for name in class_names:
            row[name] = int(counts.get(name, 0))
        row[UNDEFINED] = int(counts.get(UNDEFINED, 0))
        row["Total"] = total
        row["Right count"] = correct
        row["Right %"] = round(100.0 * correct / total, 2) if total else 0.0
        rows.append(row)

    pivot = pd.DataFrame(rows)
    month_pct = round(100.0 * right_total / row_total, 2) if row_total else 0.0
    summary = {
        "rows": row_total,
        "vehicles": len(grouped),
        "right_count": right_total,
        "right_pct": month_pct,
    }
    return pivot, summary


def write_undefined(path: Path, labels: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = sorted(labels, key=str.casefold)
    body = "\n".join(lines)
    if body:
        body += "\n"
    path.write_text(body, encoding="utf-8")
    print(f"Undefined AVC labels: {len(lines)} → {path}")


def month_sheet_name(month_key: str) -> str:
    """Excel sheet title for YYYY-MM (max 31 chars)."""
    year_s, month_s = str(month_key).split("-", 1)
    month_i = int(month_s)
    if not (1 <= month_i <= 12):
        return str(month_key)[:31]
    return f"{_MONTH_ABBR[month_i - 1]}-{year_s}"


def export_month_sheet(pivot: pd.DataFrame, class_names: list[str]) -> pd.DataFrame:
    """
    Raksha-style columns:
    Sr. No. | Vehicle Reg. No. | class… | Undefined | Total | Maximum Classification | Right %
    Zero class counts are left blank (same as the reference workbook).
    """
    frame = pivot.copy()
    if frame.empty:
        columns = (
            ["Sr. No.", "Vehicle Reg. No."]
            + list(class_names)
            + [UNDEFINED, "Total", "Maximum Classification", "Right %"]
        )
        return pd.DataFrame(columns=columns)

    frame.insert(0, "Sr. No.", range(1, len(frame) + 1))
    frame = frame.rename(
        columns={
            "VEH REG NO": "Vehicle Reg. No.",
            "Right count": "Maximum Classification",
        }
    )
    blankable = list(class_names) + [UNDEFINED]
    for col in blankable:
        if col in frame.columns:
            frame[col] = frame[col].replace(0, pd.NA)
    ordered = (
        ["Sr. No.", "Vehicle Reg. No."]
        + [c for c in class_names if c in frame.columns]
        + [c for c in (UNDEFINED, "Total", "Maximum Classification", "Right %") if c in frame.columns]
    )
    return frame[ordered]


def write_avc_accuracy_workbook(
    path: Path,
    month_pivots: dict[str, pd.DataFrame],
    class_names: list[str],
    summary_rows: list[dict],
) -> Path:
    """One sheet per calendar month; Summary sheet with monthly right-%."""
    path.parent.mkdir(parents=True, exist_ok=True)
    used_names: set[str] = set()
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for month_key in sorted(month_pivots):
            sheet = month_sheet_name(month_key)
            # Avoid duplicate sheet names if the key is somehow repeated.
            base = sheet
            suffix = 2
            while sheet.casefold() in used_names:
                sheet = f"{base[:28]}_{suffix}"
                suffix += 1
            used_names.add(sheet.casefold())
            export_month_sheet(month_pivots[month_key], class_names).to_excel(
                writer, sheet_name=sheet, index=False
            )
        if summary_rows:
            summary_df = pd.DataFrame(summary_rows)[
                ["year", "month", "rows", "vehicles", "right_count", "right_pct"]
            ]
            summary_df.to_excel(writer, sheet_name="Summary", index=False)
    print(f"Wrote AVC accuracy workbook ({len(month_pivots)} month sheet(s)): {path}")
    return path


def _analytics_connection_kwargs() -> dict:
    # Docker: Compose injects Website/backend/.env into the process (file may be absent).
    values = dotenv_values(WEBSITE_ENV) if WEBSITE_ENV.is_file() else {}
    host = str(values.get("DB_HOST") or os.getenv("DB_HOST") or "").strip()
    port = str(values.get("DB_PORT") or os.getenv("DB_PORT") or "5432").strip()
    user = str(values.get("DB_USER") or os.getenv("DB_USER") or "").strip()
    password = str(
        values.get("DB_PASSWORD")
        if values.get("DB_PASSWORD") is not None
        else os.getenv("DB_PASSWORD", "")
    )
    database = (
        str(values.get("NHIT_DB") or "").strip()
        or str(values.get("ANALYTICS_DB_NAME") or os.getenv("ANALYTICS_DB_NAME") or "").strip()
        or str(values.get("Toll_Analytics_DB") or os.getenv("Toll_Analytics_DB") or "").strip()
        or str(values.get("DB_NAME") or os.getenv("DB_NAME") or "").strip()
    )
    if not host and not WEBSITE_ENV.is_file():
        raise FileNotFoundError(
            f"Env file not found: {WEBSITE_ENV} (and DB_HOST not in process env)"
        )
    missing = [
        name
        for name, value in (
            ("DB_HOST", host),
            ("DB_PORT", port),
            ("DB_USER", user),
            ("DB_NAME", database),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required keys in {WEBSITE_ENV}: {', '.join(missing)}")
    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": password,
        "database": database,
    }


def update_exception_metrics(
    rows: list[dict],
    plaza_identifier: str,
    *,
    dry_run: bool = False,
) -> None:
    """Store only the monthly right-class percentage for exception type 11."""
    plaza = str(plaza_identifier or "").strip()
    if not plaza:
        raise RuntimeError(
            "Set PLAZA_IDENTIFIER at the top of Main_E11.py. "
            "The month files were written, but audit metrics were not updated."
        )
    if not rows:
        print("No monthly percentages to write.")
        return

    kwargs = _analytics_connection_kwargs()
    metrics_table = _metrics_table_name()
    print(f"Target DB: {kwargs['database']}.{metrics_table}")
    print(f"plaza_identifier: {plaza}")
    print(f"exception_type_id: {EXCEPTION_TYPE_ID}")
    print(f"Months to sync: {len(rows)}" + (" (dry run)" if dry_run else ""))
    upsert_sql = f"""
        INSERT INTO {metrics_table} (
            plaza_identifier, exception_type_id, year, month,
            percentage, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (plaza_identifier, exception_type_id, year, month)
        DO UPDATE SET
            percentage = EXCLUDED.percentage,
            total_amount = NULL,
            total_count = NULL,
            updated_at = NOW()
    """
    with psycopg2.connect(**kwargs) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT code FROM audit_exception_types WHERE id = %s",
                (EXCEPTION_TYPE_ID,),
            )
            found = cursor.fetchone()
            if found is None:
                raise RuntimeError(
                    f"audit_exception_types has no id {EXCEPTION_TYPE_ID}."
                )
            print(f"Exception code: {found[0]}")
            cursor.execute(
                "SELECT 1 FROM plazas WHERE plaza_identifier = %s",
                (plaza,),
            )
            if cursor.fetchone() is None:
                raise RuntimeError(f"plaza_identifier {plaza!r} was not found in plazas.")
            for row in rows:
                percentage = Decimal(str(row["right_pct"])).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                print(
                    f"  {int(row['year'])}-{int(row['month']):02d}: "
                    f"percentage={percentage}%"
                    + (" [dry-run]" if dry_run else "")
                )
                if not dry_run:
                    cursor.execute(
                        upsert_sql,
                        (
                            plaza,
                            EXCEPTION_TYPE_ID,
                            int(row["year"]),
                            int(row["month"]),
                            percentage,
                        ),
                    )
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    print(f"Updated {len(rows)} month(s).")


def download_vrn(entity_name: str, from_date: str, to_date: str) -> list[Path]:
    vrn = _load_module(E4_VRN_PATH, "e4_vrn_download_merge")
    vrn.load_env()
    start, end = vrn.validate_interval(from_date, to_date)
    folder = Path(DOWNLOAD_FOLDER)
    folder.mkdir(parents=True, exist_ok=True)
    print("Connecting to DB for VRN…")

    with psycopg2.connect(**vrn.connection_kwargs()) as conn:
        paths, _stats = vrn.download_vrn_files(
            conn,
            entity_name=entity_name,
            start=start,
            end=end,
            output_folder=folder,
            skip_existing=True,
        )
    if not paths:
        raise FileNotFoundError(
            f"No VRN files for entity={entity_name!r} "
            f"{start.isoformat()} → {end.isoformat()}"
        )
    return paths


def main() -> int:
    apply_website_env_overrides()
    entity_name = str(ENTITY_NAME).strip()
    if not entity_name:
        raise RuntimeError("Set ENTITY_NAME at the top of Main_E11.py.")

    print("=" * 60)
    print("E11 — AVC accuracy workbook (per-vehicle pivot, one sheet per month)")
    print(f"ENTITY_NAME = {entity_name!r}")
    print(f"PLAZA_IDENTIFIER = {PLAZA_IDENTIFIER!r}")
    print(f"VRN_INPUT_FOLDER = {VRN_INPUT_FOLDER!r}")
    print(f"Metrics_DB_Update = {Metrics_DB_Update}")
    print(f"UPLOAD_OUTPUT_TO_S3 = {UPLOAD_OUTPUT_TO_S3}")
    print(f"DB_DRY_RUN = {DB_DRY_RUN}")
    if PERIOD_YEAR and PERIOD_MONTH:
        print(f"PERIOD = {PERIOD_YEAR}-{PERIOD_MONTH:02d} (pipeline rollup)")
    print("=" * 60)
    config = load_config()
    date_order = date_order_for(entity_name, config)
    print(f"Date order for {entity_name}: {date_order}")

    if str(VRN_INPUT_FOLDER or "").strip():
        paths = list_vrn_files(Path(VRN_INPUT_FOLDER))
        print(f"Using {len(paths)} local VRN file(s) from {VRN_INPUT_FOLDER}")
    else:
        paths = download_vrn(entity_name, FROM_DATE, TO_DATE)

    months, undefined_labels, class_names = month_frames(paths, config, date_order)

    if not months:
        print("No dated VRN rows in this range.")
        write_undefined(OUTPUT_DIR / "undefined_avc.txt", undefined_labels)
        return 0

    out_dir = Path(OUTPUT_DIR) / entity_name
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    month_pivots: dict[str, pd.DataFrame] = {}
    for month_key in sorted(months):
        pivot, summary = build_month_pivot(months[month_key], class_names)
        month_pivots[month_key] = pivot
        year, month = month_key.split("-")
        summary_rows.append(
            {
                "year": int(year),
                "month": int(month),
                "rows": summary["rows"],
                "vehicles": summary["vehicles"],
                "right_count": summary["right_count"],
                "right_pct": summary["right_pct"],
            }
        )
        print(
            f"{month_key}: rows={summary['rows']:,}, "
            f"vehicles={summary['vehicles']:,}, "
            f"right {summary['right_count']:,} / {summary['rows']:,} "
            f"= {summary['right_pct']:.2f}%"
        )

    # Local summary CSV kept for debugging; S3 upload uses the detail workbook.
    summary_path = out_dir / "monthly_right_avc.csv"
    pd.DataFrame(summary_rows).to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"Wrote: {summary_path}")

    workbook_path = out_dir / f"{entity_name}_avc_accuracy.xlsx"
    write_avc_accuracy_workbook(
        workbook_path, month_pivots, class_names, summary_rows
    )
    write_undefined(out_dir / "undefined_avc.txt", undefined_labels)

    plaza_id = str(PLAZA_IDENTIFIER or "").strip()
    dry_run = bool(DB_DRY_RUN)
    pipeline_period = PERIOD_YEAR is not None and PERIOD_MONTH is not None

    # Pipeline: one metrics/S3 month for the batch period (weighted right %).
    metrics_rows = summary_rows
    if pipeline_period:
        total_rows = sum(int(r["rows"]) for r in summary_rows)
        total_right = sum(int(r["right_count"]) for r in summary_rows)
        total_vehicles = sum(int(r["vehicles"]) for r in summary_rows)
        right_pct = (
            round(100.0 * total_right / total_rows, 2) if total_rows else 0.0
        )
        metrics_rows = [
            {
                "year": int(PERIOD_YEAR),
                "month": int(PERIOD_MONTH),
                "rows": total_rows,
                "vehicles": total_vehicles,
                "right_count": total_right,
                "right_pct": right_pct,
            }
        ]
        print(
            f"Pipeline period {PERIOD_YEAR}-{PERIOD_MONTH:02d}: "
            f"rows={total_rows:,}, right {total_right:,} / {total_rows:,} "
            f"= {right_pct:.2f}%"
        )

    if Metrics_DB_Update:
        print("-" * 60)
        print(
            f"Updating {_metrics_table_name()} "
            f"(exception_type_id={EXCEPTION_TYPE_ID})…"
        )
        update_exception_metrics(metrics_rows, plaza_id, dry_run=dry_run)
    else:
        print("Metrics_DB_Update=False — audit_exception_metrics not updated.")

    if not UPLOAD_OUTPUT_TO_S3:
        print("UPLOAD_OUTPUT_TO_S3=False — output file not uploaded.")
        return 0

    if not plaza_id:
        raise RuntimeError("PLAZA_IDENTIFIER is required for S3 upload.")
    if pipeline_period:
        month_periods = [(int(PERIOD_YEAR), int(PERIOD_MONTH))]
    else:
        month_periods = [(int(row["year"]), int(row["month"])) for row in summary_rows]
    label = month_label_from_periods(month_periods)
    print("-" * 60)
    print(
        f"Uploading {workbook_path.name} to S3 "
        f"(month_label={label!r}, months={len(month_periods)}, "
        f"sheets={len(month_pivots)})…"
    )
    upload_exception_output(
        workbook_path,
        plaza_id,
        exception_type_id=int(EXCEPTION_TYPE_ID),
        month_label=label,
        dry_run=dry_run,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
