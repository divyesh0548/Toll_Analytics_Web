"""
E9 — Unsettled ETC amounts by month.

1. Read ETC files from ETC_INPUT_FOLDER.
2. Keep the columns listed in e9_config.json.
3. Keep rows whose Settlement Type is UNSETTLED and write that file.
4. Group by the month of Reader Read Time.
5. Count rows and sum Amount. Skip amount 0, empty, or NA.
6. Write audit_exception_metrics for PLAZA_IDENTIFIER, exception id 9.
   An existing year+month is updated only when the new count or amount is greater.

Run:
  1. Set ETC_INPUT_FOLDER and PLAZA_IDENTIFIER below
  2. python Main_E9.py
"""

from __future__ import annotations

import json
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "e9_config.json"
WEBSITE_ENV = BASE_DIR.parent.parent / "Website" / "backend" / ".env"

ETC_INPUT_FOLDER = r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E9\ETC"
PLAZA_IDENTIFIER = "94ecdec1-550c-4b4c-a94d-1df3b5fb4ac6"
EXCEPTION_TYPE_ID = 9
OUTPUT_FILE = BASE_DIR / "output" / "e9_unsettled.csv"

COLUMN_KEYS = ("reader_read_time", "settlement_type", "amount")

EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".csv"}
HEADER_SCAN_ROWS = 25

_BLANK = {"", "na", "n/a", "null", "none", "nat", "nan", "-"}
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
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
    missing = [
        key
        for key in (*COLUMN_KEYS, "unsettled_value")
        if not str(config.get(key) or "").strip()
    ]
    if missing:
        raise RuntimeError(f"{path.name} is missing: {', '.join(missing)}")
    return config


def column_name(config: dict, key: str) -> str:
    return str(config[key]).strip()


def column_names(config: dict) -> tuple[str, str, str]:
    return tuple(column_name(config, key) for key in COLUMN_KEYS)


def list_etc_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise FileNotFoundError(
            f"ETC folder not found: {folder}\n"
            "Set ETC_INPUT_FOLDER at the top of Main_E9.py."
        )
    files = sorted(
        path
        for path in folder.rglob("*")
        if path.is_file()
        and path.suffix.lower() in EXCEL_EXTENSIONS
        and not path.name.startswith("~$")
    )
    if not files:
        raise FileNotFoundError(f"No ETC files in {folder}")
    return files


def detect_header_row(df_raw: pd.DataFrame, names: tuple[str, str, str]) -> int:
    wanted = {_header_key(name) for name in names}
    limit = min(HEADER_SCAN_ROWS, len(df_raw))
    best_idx = None
    best_score = -1
    for row_idx in range(limit):
        cells = {_header_key(value) for value in df_raw.iloc[row_idx].tolist()}
        cells.discard("")
        score = sum(1 for key in wanted if key in cells)
        if score > best_score:
            best_score = score
            best_idx = row_idx
    if best_idx is None or best_score < 1:
        raise LookupError(", ".join(names))
    return best_idx


def missing_column_names(headers: list[str], names: tuple[str, str, str]) -> list[str]:
    found = {_header_key(header) for header in headers}
    return [name for name in names if _header_key(name) not in found]


def resolve_header(headers: list[str], name: str) -> str:
    key = _header_key(name)
    for header in headers:
        if _header_key(header) == key:
            return header
    raise LookupError(name)


def read_etc_file(path: Path, config: dict) -> pd.DataFrame:
    print(f"Reading: {path.name}")
    names = column_names(config)
    time_name, type_name, amount_name = names
    if path.suffix.lower() == ".csv":
        raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    else:
        raw = pd.read_excel(path, sheet_name=0, header=None, dtype=str)
    if raw.empty:
        raise ValueError(f"File is empty: {path.name}")
    try:
        header_idx = detect_header_row(raw, names)
    except LookupError as exc:
        raise LookupError(f"{path.name}: not detected: {exc}") from exc
    headers = [_header_cell(value) for value in raw.iloc[header_idx].tolist()]
    while headers and headers[-1] == "":
        headers.pop()
    missing = missing_column_names(headers, names)
    if missing:
        raise LookupError(f"{path.name}: not detected: {', '.join(missing)}")
    body = raw.iloc[header_idx + 1 :, : len(headers)].copy()
    body.columns = headers
    body = body.dropna(how="all").reset_index(drop=True)
    time_col = resolve_header(headers, time_name)
    type_col = resolve_header(headers, type_name)
    amount_col = resolve_header(headers, amount_name)
    print(f"  Header at row {header_idx + 1} ({len(body)} rows)")
    return pd.DataFrame(
        {
            time_name: body[time_col].map(_header_cell),
            type_name: body[type_col].map(_header_cell),
            amount_name: body[amount_col].map(_header_cell),
        }
    )


def is_unsettled(value, expected: str) -> bool:
    return _header_key(value) == _header_key(expected)


def parse_datetime(value) -> datetime | None:
    text = _header_cell(value)
    if text.casefold() in _BLANK:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    parsed = pd.to_datetime(text, dayfirst=False, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def parse_amount(value) -> float | None:
    """None when the amount must not be counted: empty, NA, or zero."""
    text = _header_cell(value).replace(",", "").replace("₹", "")
    if text.casefold() in _BLANK:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if abs(number) <= 1e-9:
        return None
    return number


def monthly_totals(unsettled: pd.DataFrame) -> list[dict]:
    buckets: dict[tuple[int, int], dict] = defaultdict(lambda: {"rows": 0, "amount": 0.0})
    skipped_date = 0
    skipped_amount = 0
    for record in unsettled.itertuples(index=False):
        amount = parse_amount(record[2])
        if amount is None:
            skipped_amount += 1
            continue
        when = parse_datetime(record[0])
        if when is None:
            skipped_date += 1
            continue
        bucket = buckets[(when.year, when.month)]
        bucket["rows"] += 1
        bucket["amount"] += amount
    print(f"Skipped for totals — amount 0/empty/NA: {skipped_amount}, unreadable time: {skipped_date}")
    rows = []
    for (year, month), bucket in sorted(buckets.items()):
        rows.append(
            {
                "year": year,
                "month": month,
                "total_count": bucket["rows"],
                "total_amount": round(bucket["amount"], 2),
            }
        )
        print(
            f"  {year}-{month:02d}: count={bucket['rows']:,}, "
            f"amount={bucket['amount']:,.2f}"
        )
    return rows


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


def update_exception_metrics(rows: list[dict], plaza_identifier: str) -> None:
    plaza = str(plaza_identifier or "").strip()
    if not plaza:
        raise RuntimeError(
            "Set PLAZA_IDENTIFIER at the top of Main_E9.py. "
            "The unsettled file was written, but audit metrics were not updated."
        )
    if not rows:
        print("No monthly totals to write.")
        return

    kwargs = _analytics_connection_kwargs()
    print(f"Target DB: {kwargs['database']}.audit_exception_metrics")
    print(f"plaza_identifier: {plaza}")
    print(f"exception_type_id: {EXCEPTION_TYPE_ID}")

    insert_sql = """
        INSERT INTO audit_exception_metrics (
            plaza_identifier, exception_type_id, year, month,
            total_amount, total_count, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
    """
    update_sql = """
        UPDATE audit_exception_metrics
        SET total_amount = %s,
            total_count = %s,
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
                """
                SELECT year, month, total_count, total_amount
                FROM audit_exception_metrics
                WHERE plaza_identifier = %s AND exception_type_id = %s
                """,
                (plaza, EXCEPTION_TYPE_ID),
            )
            existing = {
                (int(year), int(month)): (int(count or 0), Decimal(str(amount or 0)))
                for year, month, count, amount in cursor.fetchall()
            }
            for row in rows:
                year = int(row["year"])
                month = int(row["month"])
                new_count = int(row["total_count"])
                new_amount = Decimal(str(row["total_amount"])).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                current = existing.get((year, month))
                if current is None:
                    print(f"  {year}-{month:02d}: INSERT count={new_count:,}, amount={new_amount:,.2f}")
                    cursor.execute(
                        insert_sql,
                        (plaza, EXCEPTION_TYPE_ID, year, month, new_amount, new_count),
                    )
                    continue
                old_count, old_amount = current
                if new_count > old_count or new_amount > old_amount:
                    print(
                        f"  {year}-{month:02d}: UPDATE "
                        f"count {old_count:,} -> {new_count:,}, "
                        f"amount {old_amount:,.2f} -> {new_amount:,.2f}"
                    )
                    cursor.execute(
                        update_sql,
                        (new_amount, new_count, plaza, EXCEPTION_TYPE_ID, year, month),
                    )
                    continue
                print(
                    f"  {year}-{month:02d}: KEEP "
                    f"stored count={old_count:,}, amount={old_amount:,.2f}"
                )
        conn.commit()


def main() -> int:
    print("=" * 60)
    print("E9 — UNSETTLED ETC rows by month")
    print("=" * 60)
    config = load_config()
    unsettled_value = column_name(config, "unsettled_value")
    frames = []
    for path in list_etc_files(Path(ETC_INPUT_FOLDER)):
        try:
            frames.append(read_etc_file(path, config))
        except (zipfile.BadZipFile, OSError) as exc:
            print(f"SKIP corrupt file {path.name}: {exc}")
    if not frames:
        raise RuntimeError("No readable ETC files.")
    merged = pd.concat(frames, ignore_index=True)
    type_name = column_name(config, "settlement_type")
    unsettled = merged.loc[merged[type_name].map(lambda value: is_unsettled(value, unsettled_value))].copy()
    print(f"UNSETTLED rows: {len(unsettled)} of {len(merged)}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    unsettled.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"Wrote: {OUTPUT_FILE}")

    totals = monthly_totals(unsettled)
    update_exception_metrics(totals, PLAZA_IDENTIFIER)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
