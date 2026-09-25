"""
Write E10 segment totals from the merged output into audit_exception_metrics.

Segments:
  E10-A  Lane/Chg Standard Weight is less than Std Weight
  E10-B  Lane/Chg Standard Weight is greater than or equal to Std Weight,
         and SWB Wt/Std. Weight is zero
  E10-C  Lane/Chg Standard Weight is greater than or equal to Std Weight,
         and SWB Wt/Std. Weight is not zero
  Rows with a blank or non-numeric weight needed for that test are not counted.

Each read_datetime month is one year+month row. Amount is the sum of
Applicable Rate. E10 itself is stored as the sum of A, B, and C for that month.

Standalone:
  Set PLAZA_IDENTIFIER (and CSV_PATH if not the default output), then:
    python Update_DB_E10.py
  Or:
    python Update_DB_E10.py --csv path\\to\\e10_vrn_etc_merged.csv --plaza <plaza_identifier>

Main_E10.py calls update_e10_metrics() after it writes the merged CSV.
The analytics database name is read from Website/backend/.env (DB_NAME),
not from a DB_NAME that Main_E10 remaps to the submissions database.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import dotenv_values
from psycopg2.extras import RealDictCursor

BASE_DIR = Path(__file__).resolve().parent
WEBSITE_ENV = BASE_DIR.parent.parent / "Website" / "backend" / ".env"
DEFAULT_CSV = BASE_DIR / "output" / "e10_vrn_etc_merged.csv"

# --- Standalone inputs (edit these, or pass --csv and --plaza) ---
PLAZA_IDENTIFIER = "94ecdec1-550c-4b4c-a94d-1df3b5fb4ac6"
CSV_PATH = DEFAULT_CSV

SWB_COLUMN = "SWB Wt/Std. Weight"
LANE_STD_COLUMN = "Lane/Chg Standard Weight"
STD_COLUMN = "Std Weight"
RATE_COLUMN = "Applicable Rate"
DATETIME_COLUMN = "read_datetime"

SEGMENT_CODES = {
    "A": "E10-A",
    "B": "E10-B",
    "C": "E10-C",
}
PARENT_CODE = "E10"
SEGMENT_LABELS = {
    "E10-A": ("Lane/Chg standard weight less than standard weight", 1),
    "E10-B": (
        "Lane/Chg standard weight at or above standard weight and SWB weight is zero",
        2,
    ),
    "E10-C": (
        "Lane/Chg standard weight at or above standard weight and SWB weight is not zero",
        3,
    ),
}

_NUMBER_BLANK = {"", "na", "n/a", "null", "none", "-", "nan"}
_DATETIME_FORMATS = (
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)
_WEIGHT_EPS = 1e-6


def parse_number(value) -> float | None:
    text = str(value if value is not None else "").strip().replace(",", "")
    if text.lower() in _NUMBER_BLANK:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_read_datetime(value) -> datetime | None:
    text = re.sub(r"\s+", " ", str(value if value is not None else "").strip())
    if not text or text.lower() in _NUMBER_BLANK:
        return None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def classify_segment(
    lane_std: float | None,
    std: float | None,
    swb: float | None,
) -> str | None:
    """Return A, B, C, or None when the row must not be counted."""
    if lane_std is None or std is None:
        return None
    if lane_std + _WEIGHT_EPS < std:
        return "A"
    if swb is None:
        return None
    if abs(swb) <= _WEIGHT_EPS:
        return "B"
    return "C"


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def aggregate_segments(csv_path: Path) -> tuple[list[dict], dict[str, int]]:
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"E10 output not found: {path}")

    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = [
        name
        for name in (SWB_COLUMN, LANE_STD_COLUMN, STD_COLUMN, RATE_COLUMN, DATETIME_COLUMN)
        if name not in frame.columns
    ]
    if missing:
        raise RuntimeError(
            f"{path.name} is missing column(s): {', '.join(missing)}"
        )

    totals: dict[tuple[str, int, int], dict] = defaultdict(
        lambda: {"count": 0, "amount": 0.0}
    )
    stats = {
        "rows": len(frame),
        "counted": 0,
        "skipped_weight": 0,
        "skipped_datetime": 0,
    }

    for record in frame.to_dict(orient="records"):
        segment = classify_segment(
            parse_number(record.get(LANE_STD_COLUMN)),
            parse_number(record.get(STD_COLUMN)),
            parse_number(record.get(SWB_COLUMN)),
        )
        if segment is None:
            stats["skipped_weight"] += 1
            continue
        when = parse_read_datetime(record.get(DATETIME_COLUMN))
        if when is None:
            stats["skipped_datetime"] += 1
            continue
        rate = parse_number(record.get(RATE_COLUMN))
        bucket = totals[(segment, when.year, when.month)]
        bucket["count"] += 1
        bucket["amount"] += 0.0 if rate is None else rate
        stats["counted"] += 1

    months = {(year, month) for _segment, year, month in totals}
    rows: list[dict] = []
    for segment, year, month in sorted(totals):
        bucket = totals[(segment, year, month)]
        rows.append(
            {
                "code": SEGMENT_CODES[segment],
                "year": year,
                "month": month,
                "total_count": bucket["count"],
                "total_amount": _money(bucket["amount"]),
            }
        )
    for year, month in sorted(months):
        count = 0
        amount = Decimal("0.00")
        for segment_code in SEGMENT_CODES.values():
            match = next(
                (
                    row
                    for row in rows
                    if row["code"] == segment_code
                    and row["year"] == year
                    and row["month"] == month
                ),
                None,
            )
            if match is None:
                continue
            count += int(match["total_count"])
            amount += match["total_amount"]
        rows.append(
            {
                "code": PARENT_CODE,
                "year": year,
                "month": month,
                "total_count": count,
                "total_amount": amount,
            }
        )
    rows.sort(key=lambda row: (row["year"], row["month"], row["code"]))
    return rows, stats


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
        raise RuntimeError(
            f"Missing required keys in {WEBSITE_ENV}: {', '.join(missing)}"
        )
    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": password,
        "database": database,
    }


def _require_parent_column(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'audit_exception_types'
              AND column_name = 'parent_id'
            """
        )
        if cursor.fetchone() is None:
            raise RuntimeError(
                "audit_exception_types.parent_id is missing. "
                "Apply Website migration 0016_audit_e10_segments first."
            )


def _ensure_segment_types(conn) -> dict[str, int]:
    """Insert E10-A/B/C under E10 when missing. Returns code -> id."""
    _require_parent_column(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            "SELECT id FROM audit_exception_types WHERE code = %s",
            (PARENT_CODE,),
        )
        parent = cursor.fetchone()
        if parent is None:
            raise RuntimeError("Exception type E10 was not found in audit_exception_types.")
        parent_id = int(parent["id"])
        for code, (label, sort_order) in SEGMENT_LABELS.items():
            cursor.execute(
                """
                INSERT INTO audit_exception_types (
                    code, label, sort_order, is_active, is_hidden, parent_id,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, TRUE, FALSE, %s, NOW(), NOW())
                ON CONFLICT (code) DO UPDATE
                SET label = EXCLUDED.label,
                    sort_order = EXCLUDED.sort_order,
                    parent_id = EXCLUDED.parent_id,
                    is_active = TRUE,
                    updated_at = NOW()
                """,
                (code, label, sort_order, parent_id),
            )
        cursor.execute(
            """
            SELECT code, id
            FROM audit_exception_types
            WHERE code = ANY(%s)
            """,
            ([PARENT_CODE, *SEGMENT_LABELS.keys()],),
        )
        found = {row["code"]: int(row["id"]) for row in cursor.fetchall()}
    missing = [code for code in (PARENT_CODE, *SEGMENT_LABELS) if code not in found]
    if missing:
        raise RuntimeError(
            "Missing audit exception type(s): " + ", ".join(missing)
        )
    return found


def _require_plaza(conn, plaza_identifier: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM plazas WHERE plaza_identifier = %s",
            (plaza_identifier,),
        )
        if cursor.fetchone() is None:
            raise RuntimeError(
                f"plaza_identifier {plaza_identifier!r} was not found in plazas."
            )


def _upsert_metrics(conn, plaza_identifier: str, type_ids: dict[str, int], rows: list[dict]) -> None:
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
    with conn.cursor() as cursor:
        for row in rows:
            cursor.execute(
                sql,
                (
                    plaza_identifier,
                    type_ids[row["code"]],
                    int(row["year"]),
                    int(row["month"]),
                    row["total_amount"],
                    int(row["total_count"]),
                ),
            )


def update_e10_metrics(csv_path: Path | str, plaza_identifier: str) -> list[dict]:
    plaza = str(plaza_identifier or "").strip()
    if not plaza:
        raise RuntimeError("plaza_identifier is required.")

    rows, stats = aggregate_segments(Path(csv_path))
    print(
        f"E10 rows: {stats['rows']:,} | counted={stats['counted']:,} | "
        f"skipped weight={stats['skipped_weight']:,} | "
        f"skipped datetime={stats['skipped_datetime']:,}"
    )
    if not rows:
        print("No E10 segment rows to write.")
        return []

    print("Monthly totals (E10 is A + B + C):")
    for row in rows:
        print(
            f"  {row['code']} {row['year']}-{row['month']:02d}: "
            f"count={row['total_count']:,}, amount={row['total_amount']:,.2f}"
        )

    kwargs = _analytics_connection_kwargs()
    print(f"Target DB: {kwargs['database']}.audit_exception_metrics")
    print(f"plaza_identifier: {plaza}")
    with psycopg2.connect(**kwargs) as conn:
        _require_plaza(conn, plaza)
        type_ids = _ensure_segment_types(conn)
        _upsert_metrics(conn, plaza, type_ids, rows)
        conn.commit()
    print(f"Wrote {len(rows)} metric row(s).")
    return rows


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update E10, E10-A, E10-B, and E10-C monthly metrics from the merged CSV."
    )
    parser.add_argument(
        "--csv",
        default="",
        help=f"Merged E10 CSV. Default: {DEFAULT_CSV}",
    )
    parser.add_argument(
        "--plaza",
        default="",
        help="Plaza UUID. Default: PLAZA_IDENTIFIER at the top of this file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    csv_path = Path(str(args.csv).strip() or CSV_PATH)
    plaza = str(args.plaza).strip() or str(PLAZA_IDENTIFIER).strip()
    if not plaza:
        raise RuntimeError(
            "Set PLAZA_IDENTIFIER at the top of Update_DB_E10.py, or pass --plaza."
        )
    update_e10_metrics(csv_path, plaza)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
