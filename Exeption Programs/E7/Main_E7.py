"""
E7 — Local passes issued at a lower or zero charge (VC4 only).

1. Read pass files from PASS_INPUT_FOLDER.
2. Keep rows whose NPCI Vehicle Class is VC4 (e7_config.json).
3. Drop rows whose Payment Mode is IHMCL_Exemption.
4. Months = absolute calendar-month difference between Start/End Effective Date
   (day of month ignored). Start after End still yields a positive month count.
5. Monthly rate from Issuance Date: before 2026-04-01 → 350, else → 360.
6. If Months × rate ≤ Issuance Fees → drop the row.
   Else Loss = Months × rate − Issuance Fees (positive).
7. Write those rows (with Loss) as the output CSV.
8. Monthly metrics / S3 month label use Issuance Date year+month.
   Existing audit_exception_metrics rows are left unchanged (neglected).
9. Optionally upload the output file to S3.

Run:
  1. Set PASS_INPUT_FOLDER and PLAZA_IDENTIFIER below
  2. python Main_E7.py
"""

from __future__ import annotations

import json
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

CONFIG_PATH = BASE_DIR / "e7_config.json"
WEBSITE_ENV = BASE_DIR.parent.parent / "Website" / "backend" / ".env"

# --- Runtime inputs / flags (edit these) ---
PASS_INPUT_FOLDER = r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E7\pass-files"
PLAZA_IDENTIFIER = "94ecdec1-550c-4b4c-a94d-1df3b5fb4ac6"
EXCEPTION_TYPE_ID = 7
OUTPUT_FILE = BASE_DIR / "output" / "e7_vc4_loss.csv"
# Write monthly totals into audit_exception_metrics (skip months that already exist).
Metrics_DB_Update = True
DB_DRY_RUN = False
# Upload e7_vc4_loss.csv to S3 + audit_exception_output_files row.
UPLOAD_OUTPUT_TO_S3 = True

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
    return _header_cell(value).casefold()


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
    found = {
        key: resolve_column(headers, [column_name(config, key)])
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


def month_count(start: datetime, end: datetime) -> int:
    """
    Absolute calendar months between start and end months.
    Day of month is ignored. Start after End still returns a positive count.
    """
    return abs((end.year - start.year) * 12 + (end.month - start.month))


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
            losses_out.append(0.0)
            issuance_parsed.append(datetime.min)
            continue
        if issuance is None:
            bad_issuance += 1
            keep_mask.append(False)
            months_out.append(0)
            rates_out.append(0.0)
            fees_out.append(0.0)
            losses_out.append(0.0)
            issuance_parsed.append(datetime.min)
            continue
        if fee is None:
            bad_fees += 1
            keep_mask.append(False)
            months_out.append(0)
            rates_out.append(0.0)
            fees_out.append(0.0)
            losses_out.append(0.0)
            issuance_parsed.append(issuance)
            continue

        count = month_count(start, end)
        rate = monthly_rate_for_issuance(issuance, config, cutover)
        expected = count * rate
        if expected <= fee:
            dropped_no_loss += 1
            keep_mask.append(False)
            months_out.append(count)
            rates_out.append(rate)
            fees_out.append(fee)
            losses_out.append(0.0)
            issuance_parsed.append(issuance)
            continue

        loss = round(expected - fee, 2)
        keep_mask.append(True)
        months_out.append(count)
        rates_out.append(rate)
        fees_out.append(fee)
        losses_out.append(loss)
        issuance_parsed.append(issuance)

    work[months_name] = months_out
    work[rate_col] = rates_out
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


def resolve_plaza_identifier() -> str:
    plaza = str(PLAZA_IDENTIFIER or "").strip()
    if not plaza:
        raise RuntimeError(
            "Set PLAZA_IDENTIFIER at the top of Main_E7.py "
            "(required for metrics DB and S3 upload)."
        )
    return plaza


def _analytics_connection_kwargs() -> dict:
    if not WEBSITE_ENV.is_file():
        raise FileNotFoundError(f"Env file not found: {WEBSITE_ENV}")
    values = dotenv_values(WEBSITE_ENV)
    host = str(values.get("DB_HOST") or "").strip()
    port = str(values.get("DB_PORT") or "5432").strip()
    user = str(values.get("DB_USER") or "").strip()
    password = str(values.get("DB_PASSWORD") or "")
    database = (
        str(values.get("NHIT_DB") or "").strip()
        or str(values.get("ANALYTICS_DB_NAME") or "").strip()
        or str(values.get("DB_NAME") or "").strip()
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
    Insert monthly totals. If a plaza+type+year+month row already exists, neglect it
    (do not overwrite).
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
    print(f"Target DB: {kwargs['database']}.audit_exception_metrics")
    print(f"plaza_identifier: {plaza}")
    print(f"exception_type_id: {EXCEPTION_TYPE_ID}")
    print(f"Months to sync: {len(rows)}" + (" (dry run)" if dry_run else ""))

    insert_sql = """
        INSERT INTO audit_exception_metrics (
            plaza_identifier, exception_type_id, year, month,
            total_amount, total_count, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
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
                """
                SELECT year, month
                FROM audit_exception_metrics
                WHERE plaza_identifier = %s AND exception_type_id = %s
                """,
                (plaza, EXCEPTION_TYPE_ID),
            )
            existing = {(int(year), int(month)) for year, month in cursor.fetchall()}

            inserted = 0
            neglected = 0
            for row in rows:
                year = int(row["year"])
                month = int(row["month"])
                new_count = int(row["total_count"])
                new_amount = Decimal(str(row["total_amount"])).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if (year, month) in existing:
                    print(
                        f"  {year}-{month:02d}: NEGLECT (already exists) "
                        f"count={new_count:,}, amount={new_amount:,.2f}"
                    )
                    neglected += 1
                    continue
                print(
                    f"  {year}-{month:02d}: INSERT count={new_count:,}, "
                    f"amount={new_amount:,.2f}"
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
                        ),
                    )
                inserted += 1
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    print(f"Metrics: inserted={inserted}, neglected(existing)={neglected}")


def main() -> int:
    print("=" * 60)
    print("E7 — VC4 pass Loss (Issuance Date rate 350/360)")
    print(f"PASS_INPUT_FOLDER = {PASS_INPUT_FOLDER!r}")
    print(f"Metrics_DB_Update = {Metrics_DB_Update}")
    print(f"DB_DRY_RUN = {DB_DRY_RUN}")
    print(f"UPLOAD_OUTPUT_TO_S3 = {UPLOAD_OUTPUT_TO_S3}")
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

    if result.empty:
        print("No Loss rows — metrics/S3 skipped.")
        return 0

    print("-" * 60)
    print("Monthly totals from Issuance Date:")
    totals = summarize_by_issuance_month(result, loss_name)
    if not totals:
        print("No months with Loss — metrics/S3 skipped.")
        return 0

    plaza_id = resolve_plaza_identifier()
    dry_run = bool(DB_DRY_RUN)

    if Metrics_DB_Update:
        print("-" * 60)
        print(
            f"Updating audit_exception_metrics (exception_type_id={EXCEPTION_TYPE_ID}); "
            "existing months neglected…"
        )
        update_exception_metrics(totals, plaza_id, dry_run=dry_run)
    else:
        print("Metrics_DB_Update=False — audit_exception_metrics not updated.")

    if not UPLOAD_OUTPUT_TO_S3:
        print("UPLOAD_OUTPUT_TO_S3=False — output file not uploaded.")
        return 0

    month_periods = [(int(row["year"]), int(row["month"])) for row in totals]
    label = month_label_from_periods(month_periods)
    print("-" * 60)
    print(
        f"Uploading {OUTPUT_FILE.name} to S3 "
        f"(month_label={label!r}, months={len(month_periods)})…"
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
