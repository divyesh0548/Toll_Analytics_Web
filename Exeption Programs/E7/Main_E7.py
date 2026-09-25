"""
E7 — Local passes issued at a lower or zero charge (VC4 only).

1. Read pass files from PASS_INPUT_FOLDER.
2. Keep rows whose NPCI Vehicle Class is the value in e7_config.json.
3. Keep only the input columns listed in e7_config.json.
4. Months = calendar month difference (the day of the month is ignored).
   18-03-2026 → 31-12-2028 is 33 months.
5. Loss = Months × 360 − Issuance Fees. Stored only when the result is > 0.
6. Output and audit_exception_metrics are grouped by the start date's year and month.
   count = number of rows, amount = total Loss. exception_type_id is 7.

Run:
  1. Set PASS_INPUT_FOLDER and PLAZA_IDENTIFIER below
  2. python Main_E7.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "e7_config.json"

# Folder of pass Excel/CSV files.
PASS_INPUT_FOLDER = r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E7\pass-files"
# Plaza UUID in the analytics DB. Required for the metrics update.
PLAZA_IDENTIFIER = "94ecdec1-550c-4b4c-a94d-1df3b5fb4ac6"
# audit_exception_types.id for this finding.
EXCEPTION_TYPE_ID = 7
OUTPUT_FILE = BASE_DIR / "output" / "e7_vc4_loss.csv"
WEBSITE_ENV = BASE_DIR.parent.parent / "Website" / "backend" / ".env"

EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".csv"}
HEADER_SCAN_ROWS = 25

INPUT_COLUMN_KEYS = (
    "npci_vehicle_class",
    "start_effective_date",
    "end_effective_date",
    "issuance_fees",
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
    missing = [key for key in (*INPUT_COLUMN_KEYS, "loss", "vehicle_class_value") if not str(config.get(key) or "").strip()]
    if missing:
        raise RuntimeError(f"{path.name} is missing: {', '.join(missing)}")
    if "monthly_rate" not in config:
        raise RuntimeError(f"{path.name} is missing: monthly_rate")
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
    """Calendar months from start month to end month. The day is ignored."""
    return (end.year - start.year) * 12 + (end.month - start.month)


def parse_fee(value) -> float | None:
    text = _header_cell(value).replace(",", "")
    if text.casefold() in _BLANK:
        return 0.0
    text = text.replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def build_vc4_loss(df: pd.DataFrame, columns: dict[str, str], config: dict) -> pd.DataFrame:
    class_name = column_name(config, "npci_vehicle_class")
    start_name = column_name(config, "start_effective_date")
    end_name = column_name(config, "end_effective_date")
    fee_name = column_name(config, "issuance_fees")
    months_name = column_name(config, "months") if str(config.get("months") or "").strip() else "Months"
    loss_name = column_name(config, "loss")
    class_value = column_name(config, "vehicle_class_value")
    monthly_rate = float(config["monthly_rate"])

    vc4 = df.loc[df[columns["npci_vehicle_class"]].map(lambda value: is_vc4(value, class_value))].copy()
    print(f"{class_value} rows: {len(vc4)} of {len(df)}")

    work = pd.DataFrame(
        {
            class_name: vc4[columns["npci_vehicle_class"]].map(_header_cell).to_numpy(),
            start_name: vc4[columns["start_effective_date"]].map(_header_cell).to_numpy(),
            end_name: vc4[columns["end_effective_date"]].map(_header_cell).to_numpy(),
            fee_name: vc4[columns["issuance_fees"]].map(_header_cell).to_numpy(),
        }
    )

    months: list[int | None] = []
    losses: list[float | None] = []
    bad_dates = 0
    bad_fees = 0
    for record in work.itertuples(index=False):
        start = parse_datetime(record[1])
        end = parse_datetime(record[2])
        fee = parse_fee(record[3])
        if start is None or end is None:
            bad_dates += 1
            months.append(None)
            losses.append(None)
            continue
        if fee is None:
            bad_fees += 1
            months.append(month_count(start, end))
            losses.append(None)
            continue
        count = month_count(start, end)
        loss = count * monthly_rate - fee
        months.append(count)
        losses.append(round(loss, 2) if loss > 0 else None)

    work[months_name] = months
    work[loss_name] = losses
    work["_start"] = [parse_datetime(value) for value in work[start_name]]
    if bad_dates:
        print(f"Rows with an unreadable effective date ({loss_name} left blank): {bad_dates}")
    if bad_fees:
        print(f"Rows with a non-numeric issuance fee ({loss_name} left blank): {bad_fees}")
    positive = sum(1 for value in losses if value is not None)
    total = sum(value for value in losses if value is not None)
    print(f"Rows with {loss_name} > 0: {positive}")
    print(f"Total {loss_name}: {total:,.2f}")
    return summarize_by_start_month(work, loss_name)


def summarize_by_start_month(work: pd.DataFrame, loss_name: str) -> pd.DataFrame:
    """One row per start-date year and month: row count and total Loss."""
    buckets: dict[tuple[int, int], dict] = defaultdict(lambda: {"rows": 0, "loss": 0.0})
    skipped = 0
    for start, loss in zip(work["_start"], work[loss_name], strict=True):
        if start is None:
            skipped += 1
            continue
        bucket = buckets[(start.year, start.month)]
        bucket["rows"] += 1
        if loss is not None and not pd.isna(loss):
            bucket["loss"] += float(loss)
    if skipped:
        print(f"Rows with no start date (left out of the monthly file): {skipped}")

    summary = pd.DataFrame(
        [
            {
                "year": year,
                "month": month,
                "rows": bucket["rows"],
                "total_loss": round(bucket["loss"], 2),
            }
            for (year, month), bucket in sorted(buckets.items())
        ]
    )
    print(f"Start-date months: {len(summary)}")
    return summary


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


def update_exception_metrics(summary: pd.DataFrame, plaza_identifier: str) -> None:
    plaza = str(plaza_identifier or "").strip()
    if not plaza:
        raise RuntimeError(
            "Set PLAZA_IDENTIFIER at the top of Main_E7.py. "
            "The monthly file was written, but audit metrics were not updated."
        )

    kwargs = _analytics_connection_kwargs()
    print(f"Target DB: {kwargs['database']}.audit_exception_metrics")
    print(f"plaza_identifier: {plaza}")
    print(f"exception_type_id: {EXCEPTION_TYPE_ID}")

    sql = """
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
        ON CONFLICT ON CONSTRAINT uq_audit_exception_metrics_plaza_type_period
        DO UPDATE SET
            total_amount = EXCLUDED.total_amount,
            total_count = EXCLUDED.total_count,
            updated_at = NOW()
    """
    with psycopg2.connect(**kwargs) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT code
                FROM audit_exception_types
                WHERE id = %s
                """,
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

            for record in summary.itertuples(index=False):
                amount = Decimal(str(record.total_loss)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                print(
                    f"  {int(record.year)}-{int(record.month):02d}: "
                    f"count={int(record.rows):,}, amount={amount:,.2f}"
                )
                cursor.execute(
                    sql,
                    (
                        plaza,
                        EXCEPTION_TYPE_ID,
                        int(record.year),
                        int(record.month),
                        amount,
                        int(record.rows),
                    ),
                )
        conn.commit()
    print(f"Wrote {len(summary)} metric row(s).")


def main() -> int:
    print("=" * 60)
    print("E7 — VC4 pass months × 360 − issuance fee")
    print("=" * 60)
    config = load_config()
    keywords = [column_name(config, key) for key in INPUT_COLUMN_KEYS]
    folder = Path(PASS_INPUT_FOLDER)
    frames = [read_pass_file(path, keywords) for path in list_pass_files(folder)]
    merged = pd.concat(frames, ignore_index=True)
    print(f"Merged pass rows: {len(merged)}")
    columns = require_columns(merged, config)
    result = build_vc4_loss(merged, columns, config)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"Wrote: {OUTPUT_FILE}")
    update_exception_metrics(result, PLAZA_IDENTIFIER)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
