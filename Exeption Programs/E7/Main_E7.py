"""
E7 — Local passes issued at a lower or zero charge (VC4 only).

1. Read pass files from PASS_INPUT_FOLDER.
2. Keep rows whose NPCI Vehicle Class is VC4 (e7_config.json).
3. Drop rows whose Payment Mode is IHMCL_Exemption.
4. Months = calendar-month difference between Start/End Effective Date
   (day of month ignored), minimum 1 when Start month ≤ End month.
   Rows where Start month is after End month are dropped (invalid window).
5. Monthly rate from Issuance Date: before 2026-04-01 → 350, else → 360.
6. Receivable Amt = Months × Monthly Rate.
7. If Receivable Amt ≤ Issuance Fees → drop the row.
   Else Loss = Receivable Amt − Issuance Fees (positive).
8. Write those rows (Receivable Amt left of Loss) as the output CSV.
9. Monthly metrics / S3 month label use Issuance Date year+month.
   Existing audit_exception_metrics rows are always overwritten.
   Empty Loss still writes zero metrics (pipeline period or empty_filter) and
   uploads the (header-only) CSV so the website has a downloadable output.
10. Optionally upload the output file to S3.

Run:
  1. Set PASS_INPUT_FOLDER and PLAZA_IDENTIFIER below
  2. python Main_E7.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
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


def _metrics_table_name() -> str:
    name = (
        os.getenv("Exception_Metrics_Table", "").strip()
        or os.getenv("EXCEPTION_METRICS_TABLE", "").strip()
        or "audit_exception_metrics"
    )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise RuntimeError(f"Invalid Exception_Metrics_Table: {name!r}")
    return name

CONFIG_PATH = BASE_DIR / "e7_config.json"
WEBSITE_ENV = BASE_DIR.parent.parent / "Website" / "backend" / ".env"

# --- Runtime inputs / flags (Website overrides via E7_* env) ---
PASS_INPUT_FOLDER = r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E7\pass-files"
PLAZA_IDENTIFIER = "94ecdec1-550c-4b4c-a94d-1df3b5fb4ac6"
EXCEPTION_TYPE_ID = 7
OUTPUT_FILE = BASE_DIR / "output" / "e7_vc4_loss.csv"
# Write monthly totals into audit_exception_metrics (skip months that already exist).
Metrics_DB_Update = True
DB_DRY_RUN = False
# Upload e7_vc4_loss.csv to S3 + audit_exception_output_files row.
UPLOAD_OUTPUT_TO_S3 = True
# Pipeline batch period (optional). When set, metrics + S3 label use this month
# (sum of the whole run) instead of splitting by Issuance Date.
PERIOD_YEAR: int | None = None
PERIOD_MONTH: int | None = None

EMPTY_FILTER_STATUS = "empty_filter"
EMPTY_FILTER_NOTES = "No VC4 Loss rows after filters"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def apply_website_env_overrides() -> None:
    """Apply E7_* env from Website job runner."""
    global PASS_INPUT_FOLDER, PLAZA_IDENTIFIER, OUTPUT_FILE
    global Metrics_DB_Update, DB_DRY_RUN, UPLOAD_OUTPUT_TO_S3
    global PERIOD_YEAR, PERIOD_MONTH

    if os.environ.get("E7_PASS_INPUT_FOLDER", "").strip():
        PASS_INPUT_FOLDER = os.environ["E7_PASS_INPUT_FOLDER"].strip()
    if os.environ.get("E7_OUTPUT_FILE", "").strip():
        OUTPUT_FILE = Path(os.environ["E7_OUTPUT_FILE"].strip())
    if os.environ.get("E7_PLAZA_IDENTIFIER", "").strip():
        PLAZA_IDENTIFIER = os.environ["E7_PLAZA_IDENTIFIER"].strip()
    if "E7_METRICS_DB_UPDATE" in os.environ:
        Metrics_DB_Update = _env_flag("E7_METRICS_DB_UPDATE", Metrics_DB_Update)
    if "E7_UPLOAD_OUTPUT_TO_S3" in os.environ:
        UPLOAD_OUTPUT_TO_S3 = _env_flag("E7_UPLOAD_OUTPUT_TO_S3", UPLOAD_OUTPUT_TO_S3)
    if "E7_DB_DRY_RUN" in os.environ:
        DB_DRY_RUN = _env_flag("E7_DB_DRY_RUN", DB_DRY_RUN)

    year_raw = os.environ.get("E7_PERIOD_YEAR", "").strip()
    month_raw = os.environ.get("E7_PERIOD_MONTH", "").strip()
    if year_raw and month_raw:
        year = int(year_raw)
        month = int(month_raw)
        if not (1990 <= year <= 2100 and 1 <= month <= 12):
            raise RuntimeError(
                f"Invalid E7_PERIOD_YEAR/MONTH: {year_raw!r}/{month_raw!r}"
            )
        PERIOD_YEAR = year
        PERIOD_MONTH = month

EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".csv"}
HEADER_SCAN_ROWS = 25

INPUT_COLUMN_KEYS = (
    "npci_vehicle_class",
    "start_effective_date",
    "end_effective_date",
    "issuance_date",
    "issuance_fees",
    "payment_mode",
)

_BLANK = {"", "na", "n/a", "null", "none", "nat", "nan", "-"}
_DATE_FORMATS = (
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def _header_cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return " ".join(text.split())


def _header_key(value) -> str:
    """Normalize so 'Issuance Fees (Rs.)' and 'Issuance Fees(Rs.)' match."""
    text = _header_cell(value).casefold()
    text = re.sub(r"\s*([()\[\]{}/_-])\s*", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open(encoding="utf-8") as handle:
        config = json.load(handle)
    text_keys = (
        *INPUT_COLUMN_KEYS,
        "loss",
        "vehicle_class_value",
        "payment_mode_exclude",
        "rate_cutover_date",
    )
    missing = [key for key in text_keys if not str(config.get(key) or "").strip()]
    for key in ("monthly_rate_before_apr_2026", "monthly_rate_from_apr_2026"):
        if key not in config:
            missing.append(key)
    if missing:
        raise RuntimeError(f"{path.name} is missing: {', '.join(missing)}")
    return config


def column_name(config: dict, key: str) -> str:
    return str(config[key]).strip()


def resolve_column(headers: list[str], aliases: list[str]) -> str | None:
    by_key = {_header_key(header): header for header in headers if _header_cell(header)}
    for alias in aliases:
        match = by_key.get(_header_key(alias))
        if match:
            return match
    return None


def list_pass_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise FileNotFoundError(
            f"Pass folder not found: {folder}\n"
            "Set PASS_INPUT_FOLDER at the top of Main_E7.py."
        )
    files = sorted(
        path
        for path in folder.iterdir()
        if path.is_file()
        and path.suffix.lower() in EXCEL_EXTENSIONS
        and not path.name.startswith("~$")
    )
    if not files:
        raise FileNotFoundError(f"No pass files in {folder}")
    return files


def detect_header_row(df_raw: pd.DataFrame, keywords: list[str]) -> int:
    keyword_keys = {_header_key(keyword) for keyword in keywords}
    min_matches = min(3, len(keyword_keys))
    limit = min(HEADER_SCAN_ROWS, len(df_raw))
    best_idx = None
    best_score = -1
    for row_idx in range(limit):
        cells = {_header_key(value) for value in df_raw.iloc[row_idx].tolist()}
        cells.discard("")
        score = sum(1 for key in keyword_keys if key in cells)
        if score > best_score:
            best_score = score
            best_idx = row_idx
    if best_idx is None or best_score < min_matches:
        raise ValueError(
            f"Header row not detected (need >= {min_matches} keyword matches; "
            f"best score={best_score})."
        )
    return best_idx


def read_pass_file(path: Path, keywords: list[str]) -> pd.DataFrame:
    print(f"Reading: {path.name}")
    if path.suffix.lower() == ".csv":
        raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    else:
        raw = pd.read_excel(path, sheet_name=0, header=None, dtype=str)
    if raw.empty:
        raise ValueError(f"File is empty: {path.name}")
    header_idx = detect_header_row(raw, keywords)
    headers = [_header_cell(value) for value in raw.iloc[header_idx].tolist()]
    while headers and headers[-1] == "":
        headers.pop()
    body = raw.iloc[header_idx + 1 :, : len(headers)].copy()
    body.columns = headers
    body = body.dropna(how="all").reset_index(drop=True)
    print(f"  Header at row {header_idx + 1} ({len(headers)} columns, {len(body)} rows)")
    return body


def require_columns(df: pd.DataFrame, config: dict) -> dict[str, str]:
    headers = [str(column) for column in df.columns]
    alias_extra = {
        "issuance_fees": [
            "Issuance Fees(Rs.)",
            "Issuance Fees (Rs.)",
            "Issuance Fee(Rs.)",
            "Issuance Fee (Rs.)",
            "Issuance Fees",
        ],
    }
    found = {
        key: resolve_column(
            headers,
            [column_name(config, key), *(alias_extra.get(key) or [])],
        )
        for key in INPUT_COLUMN_KEYS
    }
    missing = [column_name(config, key) for key, column in found.items() if column is None]
    if missing:
        raise RuntimeError(
            "Missing column(s): "
            + ", ".join(missing)
            + ". Available: "
            + ", ".join(headers)
        )
    print(
        "Columns: "
        + ", ".join(f"{key}={found[key]!r}" for key in INPUT_COLUMN_KEYS)
    )
    return found


def is_vc4(value, expected: str) -> bool:
    text = _header_cell(value).upper()
    target = re.sub(r"[^A-Z0-9]", "", expected.upper())
    return re.sub(r"[^A-Z0-9]", "", text) == target


def is_excluded_payment_mode(value, excluded: str) -> bool:
    text = re.sub(r"[^A-Z0-9_]", "", _header_cell(value).upper())
    target = re.sub(r"[^A-Z0-9_]", "", excluded.upper())
    return bool(target) and text == target


def parse_datetime(value) -> datetime | None:
    text = _header_cell(value)
    if text.casefold() in _BLANK:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def month_count(start: datetime, end: datetime) -> int | None:
    """
    Calendar months between start and end months (day ignored).

    Same calendar month → 1 (a one-month pass must still be billed).
    Start month after End month → None (invalid / likely day-month swap in source).
    """
    if (end.year, end.month) < (start.year, start.month):
        return None
    diff = (end.year - start.year) * 12 + (end.month - start.month)
    return max(diff, 1)


def parse_fee(value) -> float | None:
    text = _header_cell(value).replace(",", "")
    if text.casefold() in _BLANK:
        return 0.0
    text = text.replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_cutover_date(config: dict) -> date:
    raw = str(config.get("rate_cutover_date") or "2026-04-01").strip()
    parsed = parse_datetime(raw)
    if parsed is None:
        raise RuntimeError(f"Invalid rate_cutover_date in config: {raw!r}")
    return parsed.date()


def monthly_rate_for_issuance(issuance: datetime, config: dict, cutover: date) -> float:
    before = float(config["monthly_rate_before_apr_2026"])
    after = float(config["monthly_rate_from_apr_2026"])
    if issuance.date() < cutover:
        return before
    return after


def build_vc4_loss(df: pd.DataFrame, columns: dict[str, str], config: dict) -> pd.DataFrame:
    class_name = column_name(config, "npci_vehicle_class")
    start_name = column_name(config, "start_effective_date")
    end_name = column_name(config, "end_effective_date")
    issuance_name = column_name(config, "issuance_date")
    fee_name = column_name(config, "issuance_fees")
    payment_name = column_name(config, "payment_mode")
    months_name = (
        column_name(config, "months")
        if str(config.get("months") or "").strip()
        else "Months"
    )
    rate_col = (
        column_name(config, "monthly_rate_column")
        if str(config.get("monthly_rate_column") or "").strip()
        else "Monthly Rate"
    )
    receivable_name = (
        column_name(config, "receivable_amt")
        if str(config.get("receivable_amt") or "").strip()
        else "Receivable Amt"
    )
    loss_name = column_name(config, "loss")
    class_value = column_name(config, "vehicle_class_value")
    exclude_payment = column_name(config, "payment_mode_exclude")
    cutover = parse_cutover_date(config)

    vc4 = df.loc[
        df[columns["npci_vehicle_class"]].map(lambda value: is_vc4(value, class_value))
    ].copy()
    print(f"{class_value} rows: {len(vc4)} of {len(df)}")

    before_pay = len(vc4)
    vc4 = vc4.loc[
        ~vc4[columns["payment_mode"]].map(
            lambda value: is_excluded_payment_mode(value, exclude_payment)
        )
    ].copy()
    print(
        f"Removed Payment Mode={exclude_payment!r}: "
        f"{before_pay - len(vc4):,} (kept {len(vc4):,})"
    )

    work = pd.DataFrame(
        {
            class_name: vc4[columns["npci_vehicle_class"]].map(_header_cell).to_numpy(),
            start_name: vc4[columns["start_effective_date"]].map(_header_cell).to_numpy(),
            end_name: vc4[columns["end_effective_date"]].map(_header_cell).to_numpy(),
            issuance_name: vc4[columns["issuance_date"]].map(_header_cell).to_numpy(),
            fee_name: vc4[columns["issuance_fees"]].map(_header_cell).to_numpy(),
            payment_name: vc4[columns["payment_mode"]].map(_header_cell).to_numpy(),
        }
    )

    months_out: list[int] = []
    rates_out: list[float] = []
    fees_out: list[float] = []
    receivable_out: list[float] = []
    losses_out: list[float] = []
    issuance_parsed: list[datetime] = []
    keep_mask: list[bool] = []

    bad_dates = 0
    bad_issuance = 0
    bad_fees = 0
    dropped_no_loss = 0

    for record in work.itertuples(index=False):
        start = parse_datetime(record[1])
        end = parse_datetime(record[2])
        issuance = parse_datetime(record[3])
        fee = parse_fee(record[4])

        if start is None or end is None:
            bad_dates += 1
            keep_mask.append(False)
            months_out.append(0)
            rates_out.append(0.0)
            fees_out.append(0.0)
            receivable_out.append(0.0)
            losses_out.append(0.0)
            issuance_parsed.append(datetime.min)
            continue
        if issuance is None:
            bad_issuance += 1
            keep_mask.append(False)
            months_out.append(0)
            rates_out.append(0.0)
            fees_out.append(0.0)
            receivable_out.append(0.0)
            losses_out.append(0.0)
            issuance_parsed.append(datetime.min)
            continue
        if fee is None:
            bad_fees += 1
            keep_mask.append(False)
            months_out.append(0)
            rates_out.append(0.0)
            fees_out.append(0.0)
            receivable_out.append(0.0)
            losses_out.append(0.0)
            issuance_parsed.append(issuance)
            continue

        count = month_count(start, end)
        rate = monthly_rate_for_issuance(issuance, config, cutover)
        receivable = round(count * rate, 2)
        if receivable <= fee:
            dropped_no_loss += 1
            keep_mask.append(False)
            months_out.append(count)
            rates_out.append(rate)
            fees_out.append(fee)
            receivable_out.append(receivable)
            losses_out.append(0.0)
            issuance_parsed.append(issuance)
            continue

        loss = round(receivable - fee, 2)
        keep_mask.append(True)
        months_out.append(count)
        rates_out.append(rate)
        fees_out.append(fee)
        receivable_out.append(receivable)
        losses_out.append(loss)
        issuance_parsed.append(issuance)

    work[months_name] = months_out
    work[rate_col] = rates_out
    # Receivable Amt = Months × Monthly Rate; keep immediately left of Loss.
    work[receivable_name] = receivable_out
    work[loss_name] = losses_out
    work["_issuance"] = issuance_parsed

    if bad_dates:
        print(f"Dropped (unreadable Start/End Effective Date): {bad_dates}")
    if bad_issuance:
        print(f"Dropped (unreadable Issuance Date): {bad_issuance}")
    if bad_fees:
        print(f"Dropped (non-numeric Issuance Fees): {bad_fees}")
    print(
        f"Dropped (Months×rate ≤ Issuance Fees): {dropped_no_loss}"
    )

    out = work.loc[keep_mask].copy().reset_index(drop=True)
    print(f"Output rows with {loss_name} > 0: {len(out)}")
    if len(out):
        print(f"Total {loss_name}: {float(out[loss_name].sum()):,.2f}")
    return out


def summarize_by_issuance_month(work: pd.DataFrame, loss_name: str) -> list[dict]:
    """One bucket per Issuance Date year/month: row count and total Loss."""
    buckets: dict[tuple[int, int], dict] = defaultdict(lambda: {"rows": 0, "loss": 0.0})
    skipped = 0
    for issuance, loss in zip(work["_issuance"], work[loss_name], strict=True):
        if issuance is None or issuance == datetime.min:
            skipped += 1
            continue
        bucket = buckets[(issuance.year, issuance.month)]
        bucket["rows"] += 1
        bucket["loss"] += float(loss)
    if skipped:
        print(f"Rows with no Issuance Date (left out of monthly totals): {skipped}")

    rows = []
    for (year, month), bucket in sorted(buckets.items()):
        rows.append(
            {
                "year": year,
                "month": month,
                "total_count": bucket["rows"],
                "total_amount": round(bucket["loss"], 2),
            }
        )
        print(
            f"  {year}-{month:02d}: count={bucket['rows']:,}, "
            f"amount={bucket['loss']:,.2f}"
        )
    print(f"Issuance-date months: {len(rows)}")
    return rows


def summarize_for_period(
    work: pd.DataFrame,
    loss_name: str,
    *,
    year: int,
    month: int,
) -> list[dict]:
    """Roll the whole run into one pipeline batch month."""
    if work is None or work.empty:
        return [
            {
                "year": int(year),
                "month": int(month),
                "total_count": 0,
                "total_amount": 0.0,
                "status": EMPTY_FILTER_STATUS,
                "notes": EMPTY_FILTER_NOTES,
            }
        ]
    count = int(len(work))
    amount = round(float(work[loss_name].sum()), 2)
    print(
        f"Pipeline period {year}-{month:02d}: count={count:,}, amount={amount:,.2f}"
    )
    return [
        {
            "year": int(year),
            "month": int(month),
            "total_count": count,
            "total_amount": amount,
            "status": None,
            "notes": None,
        }
    ]


def resolve_plaza_identifier() -> str:
    plaza = str(PLAZA_IDENTIFIER or "").strip()
    if not plaza:
        raise RuntimeError(
            "Set PLAZA_IDENTIFIER at the top of Main_E7.py "
            "(required for metrics DB and S3 upload)."
        )
    return plaza


def _analytics_connection_kwargs() -> dict:
    # Docker: Compose injects Website/backend/.env into the process (file absent).
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
    """
    Insert monthly totals. If a plaza+type+year+month row already exists,
    overwrite total_count and total_amount with the new values.
    """
    plaza = str(plaza_identifier or "").strip()
    if not plaza:
        raise RuntimeError(
            "Set PLAZA_IDENTIFIER at the top of Main_E7.py. "
            "The output file was written, but audit metrics were not updated."
        )
    if not rows:
        print("No monthly totals to write.")
        return

    kwargs = _analytics_connection_kwargs()
    metrics_table = _metrics_table_name()
    print(f"Target DB: {kwargs['database']}.{metrics_table}")
    print(f"plaza_identifier: {plaza}")
    print(f"exception_type_id: {EXCEPTION_TYPE_ID}")
    print(f"Months to sync: {len(rows)}" + (" (dry run)" if dry_run else ""))

    insert_sql = f"""
        INSERT INTO {metrics_table} (
            plaza_identifier, exception_type_id, year, month,
            total_amount, total_count, status, notes, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
    """
    update_sql = f"""
        UPDATE {metrics_table}
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

            cursor.execute(
                f"""
                SELECT year, month, total_count, total_amount
                FROM {metrics_table}
                WHERE plaza_identifier = %s AND exception_type_id = %s
                """,
                (plaza, EXCEPTION_TYPE_ID),
            )
            existing = {
                (int(year), int(month)): (int(count or 0), Decimal(str(amount or 0)))
                for year, month, count, amount in cursor.fetchall()
            }

            inserted = 0
            updated = 0
            for row in rows:
                year = int(row["year"])
                month = int(row["month"])
                new_count = int(row["total_count"])
                new_amount = Decimal(str(row["total_amount"])).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                status = row.get("status")
                notes = row.get("notes")
                if status is not None:
                    status = str(status).strip() or None
                if notes is not None:
                    notes = str(notes).strip() or None
                current = existing.get((year, month))
                if current is not None:
                    old_count, old_amount = current
                    print(
                        f"  {year}-{month:02d}: UPDATE "
                        f"count {old_count:,} -> {new_count:,}, "
                        f"amount {old_amount:,.2f} -> {new_amount:,.2f}"
                        + (f", status={status}" if status else "")
                        + (" [dry-run]" if dry_run else "")
                    )
                    if not dry_run:
                        cursor.execute(
                            update_sql,
                            (
                                new_amount,
                                new_count,
                                status,
                                notes,
                                plaza,
                                EXCEPTION_TYPE_ID,
                                year,
                                month,
                            ),
                        )
                    updated += 1
                    continue
                print(
                    f"  {year}-{month:02d}: INSERT count={new_count:,}, "
                    f"amount={new_amount:,.2f}"
                    + (f", status={status}" if status else "")
                    + (" [dry-run]" if dry_run else "")
                )
                if not dry_run:
                    cursor.execute(
                        insert_sql,
                        (
                            plaza,
                            EXCEPTION_TYPE_ID,
                            year,
                            month,
                            new_amount,
                            new_count,
                            status,
                            notes,
                        ),
                    )
                inserted += 1
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    print(f"Metrics: inserted={inserted}, updated={updated}")


def main() -> int:
    apply_website_env_overrides()
    print("=" * 60)
    print("E7 — VC4 pass Loss (Issuance Date rate 350/360)")
    print(f"PASS_INPUT_FOLDER = {PASS_INPUT_FOLDER!r}")
    print(f"Metrics_DB_Update = {Metrics_DB_Update}")
    print(f"DB_DRY_RUN = {DB_DRY_RUN}")
    print(f"UPLOAD_OUTPUT_TO_S3 = {UPLOAD_OUTPUT_TO_S3}")
    if PERIOD_YEAR and PERIOD_MONTH:
        print(f"PERIOD = {PERIOD_YEAR}-{PERIOD_MONTH:02d} (pipeline rollup)")
    print("=" * 60)

    config = load_config()
    keywords = [column_name(config, key) for key in INPUT_COLUMN_KEYS]
    folder = Path(PASS_INPUT_FOLDER)
    frames = [read_pass_file(path, keywords) for path in list_pass_files(folder)]
    merged = pd.concat(frames, ignore_index=True)
    print(f"Merged pass rows: {len(merged)}")
    columns = require_columns(merged, config)
    result = build_vc4_loss(merged, columns, config)

    loss_name = column_name(config, "loss")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    export = result.drop(columns=["_issuance"], errors="ignore")
    export.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"Wrote: {OUTPUT_FILE} ({len(export)} rows)")

    plaza_id = resolve_plaza_identifier()
    dry_run = bool(DB_DRY_RUN)
    pipeline_period = PERIOD_YEAR is not None and PERIOD_MONTH is not None

    if pipeline_period:
        print("-" * 60)
        print(
            f"Monthly totals for pipeline period "
            f"{PERIOD_YEAR}-{PERIOD_MONTH:02d}:"
        )
        totals = summarize_for_period(
            result,
            loss_name,
            year=int(PERIOD_YEAR),
            month=int(PERIOD_MONTH),
        )
    elif result.empty:
        print("No Loss rows — metrics/S3 skipped (no pipeline period set).")
        return 0
    else:
        print("-" * 60)
        print("Monthly totals from Issuance Date:")
        totals = summarize_by_issuance_month(result, loss_name)
        if not totals:
            print("No months with Loss — metrics/S3 skipped.")
            return 0

    if Metrics_DB_Update:
        print("-" * 60)
        print(
            f"Updating {_metrics_table_name()} "
            f"(exception_type_id={EXCEPTION_TYPE_ID})…"
        )
        update_exception_metrics(totals, plaza_id, dry_run=dry_run)
    else:
        print("Metrics_DB_Update=False — metrics table not updated.")

    if not UPLOAD_OUTPUT_TO_S3:
        print("UPLOAD_OUTPUT_TO_S3=False — output file not uploaded.")
        return 0

    month_periods = [(int(row["year"]), int(row["month"])) for row in totals]
    label = month_label_from_periods(month_periods)
    print("-" * 60)
    print(
        f"Uploading {OUTPUT_FILE.name} to S3 "
        f"(month_label={label!r}, rows={len(export)})…"
    )
    upload_exception_output(
        OUTPUT_FILE,
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
