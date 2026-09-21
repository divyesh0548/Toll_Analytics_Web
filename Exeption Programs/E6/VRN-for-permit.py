"""
E6 — Download ETC for a plaza/date range; export vehicle numbers by month.

1) Download/merge ETC via E4 etc-download-merge (vehicle_reg_no + read_datetime only)
2) Split rows by calendar month of Tag Read / Date & Time
3) Write one file per month with only the vehicle number column:
     {plaza}_{YYYY-MM-DD}_{YYYY-MM-DD}_vehicle_number.csv

Run:
  1. Set ENTITY_NAME, FROM_DATE, TO_DATE below
  2. python VRN-for-permit.py
     or: python VRN-for-permit.py odhaki_paipkhar 2026-01-01 2026-04-30
"""

from __future__ import annotations

import calendar
import importlib.util
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
E4_DIR = BASE_DIR.parent / "E4"
ETC_DOWNLOAD_MERGE_PATH = E4_DIR / "etc-download-merge.py"
OUTPUT_DIR = BASE_DIR / "output" / "vehicle_numbers_for_permit"

# --- Runtime inputs (edit these) ---
ENTITY_NAME = "odhaki_paipkhar"
FROM_DATE = "2026-07-01"  # inclusive YYYY-MM-DD
TO_DATE = "2026-07-31"  # inclusive YYYY-MM-DD
# If True, keep only distinct non-empty vehicle numbers within each month file.
UNIQUE_VEHICLES_PER_MONTH = True

# ETC merge: only columns needed for this export
ETC_MERGE_CONFIG = {
    "header_keywords": [
        "Veh Reg No",
        "Veh Reg No.",
        "Vehicle Reg No",
        "Date & Time",
        "Tag Read Date Time",
        "Journey Type",
        "Settlement Amount",
        "Agency Txn Id",
        "Plaza Name",
        "MOP",
    ],
    "header_scan_rows": 25,
    "min_header_matches": 2,
    "merge_columns": {
        "vehicle_reg_no": [
            "Veh Reg No",
            "Veh Reg No.",
            "Vehicle Reg No",
            "Vehicle Number",
            "Vehicle No",
            "Reg No",
            "Licence Plate No",
        ],
        "read_datetime": [
            "Tag Read Date Time",
            "Date & Time",
            "Date and Time",
            "Txn Date Time",
            "Txn Date & Time",
            "Transaction Date Time",
            "Transaction Date & Time",
            "Transaction Date",
            "Date",
        ],
    },
}


def safe_part(value: str) -> str:
    text = re.sub(r"[^\w.\-]+", "_", str(value or "").strip())
    return text.strip("._") or "plaza"


def resolve_inputs() -> tuple[str, str, str]:
    entity = ENTITY_NAME
    from_date = FROM_DATE
    to_date = TO_DATE
    if len(sys.argv) >= 2 and str(sys.argv[1]).strip():
        entity = str(sys.argv[1]).strip()
    if len(sys.argv) >= 3 and str(sys.argv[2]).strip():
        from_date = str(sys.argv[2]).strip()
    if len(sys.argv) >= 4 and str(sys.argv[3]).strip():
        to_date = str(sys.argv[3]).strip()

    entity = str(entity or "").strip()
    from_date = str(from_date or "").strip()
    to_date = str(to_date or "").strip()
    if not entity:
        entity = input("Enter plaza entity_name: ").strip()
    if not from_date:
        from_date = input("Enter FROM_DATE (YYYY-MM-DD): ").strip()
    if not to_date:
        to_date = input("Enter TO_DATE (YYYY-MM-DD): ").strip()
    if not entity or not from_date or not to_date:
        raise RuntimeError("entity_name, FROM_DATE and TO_DATE are required.")
    return entity, from_date, to_date


def load_etc_download_merge_module():
    path = ETC_DOWNLOAD_MERGE_PATH
    if not path.is_file():
        raise FileNotFoundError(f"ETC download script not found: {path}")
    spec = importlib.util.spec_from_file_location("e4_etc_download_merge", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def clip_month_range(
    month_start: date,
    month_end: date,
    overall_start: date,
    overall_end: date,
    ) -> tuple[date, date]:
    start = max(month_start, overall_start)
    end = min(month_end, overall_end)
    return start, end


def normalize_vehicle_number(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().upper()
    if text in {"", "NAN", "NONE", "NAT"}:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text)


def write_month_vehicle_file(
    month_df: pd.DataFrame,
    *,
    plaza: str,
    range_start: date,
    range_end: date,
    output_dir: Path,
     ) -> Path:
    work = month_df.copy()
    work["vehicle_reg_no"] = work["vehicle_reg_no"].map(
        lambda v: str(v).strip() if v is not None and not (isinstance(v, float) and pd.isna(v)) else ""
    )
    work = work.loc[work["vehicle_reg_no"].ne("")].copy()

    if UNIQUE_VEHICLES_PER_MONTH:
        work["_key"] = work["vehicle_reg_no"].map(normalize_vehicle_number)
        work = (
            work.loc[work["_key"].ne("")]
            .drop_duplicates(subset=["_key"], keep="first")
            .drop(columns=["_key"])
        )

    out = pd.DataFrame({"vehicle_reg_no": work["vehicle_reg_no"].tolist()})
    name = (
        f"{safe_part(plaza)}_{range_start.isoformat()}_{range_end.isoformat()}"
        f"_vehicle_number.csv"
    )
    path = output_dir / name
    out.to_csv(path, index=False, encoding="utf-8-sig")
    print(
        f"  Wrote {path.name}: {len(out):,} vehicle number(s) "
        f"({range_start.isoformat()} → {range_end.isoformat()})"
    )
    return path


def main() -> int:
    print("=" * 60)
    print("E6 — ETC → monthly vehicle numbers for permit")
    print("=" * 60)

    entity_name, from_date, to_date = resolve_inputs()
    print(f"plaza / entity_name: {entity_name}")
    print(f"date range: {from_date} → {to_date}")
    print(f"UNIQUE_VEHICLES_PER_MONTH = {UNIQUE_VEHICLES_PER_MONTH}")

    overall_start = date.fromisoformat(from_date)
    overall_end = date.fromisoformat(to_date)
    if overall_end < overall_start:
        raise RuntimeError("TO_DATE must be on or after FROM_DATE.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("-" * 60)
    print("Downloading / merging ETC…")
    etc_mod = load_etc_download_merge_module()
    etc_path = etc_mod.run_etc_download_merge(
        entity_name,
        from_date,
        to_date,
        merged_output_dir=OUTPUT_DIR,
        config=ETC_MERGE_CONFIG,
    )
    if etc_path is None:
        raise RuntimeError("ETC download finished without a merged file path.")
    print(f"Merged ETC: {etc_path}")

    etc_df = pd.read_csv(etc_path, dtype=str, keep_default_na=False)
    if "vehicle_reg_no" not in etc_df.columns:
        raise RuntimeError(
            "Merged ETC missing vehicle_reg_no. "
            f"Columns: {list(etc_df.columns)}"
        )
    if "read_datetime" not in etc_df.columns:
        raise RuntimeError(
            "Merged ETC missing read_datetime (needed to split by month). "
            f"Columns: {list(etc_df.columns)}"
        )

    etc_df = etc_df.copy()
    etc_df["_dt"] = pd.to_datetime(
        etc_df["read_datetime"], errors="coerce", format="mixed"
    )
    before = len(etc_df)
    etc_df = etc_df.dropna(subset=["_dt"]).copy()
    print(f"ETC rows with valid datetime: {len(etc_df):,}/{before:,}")

    etc_df["_year"] = etc_df["_dt"].dt.year.astype(int)
    etc_df["_month"] = etc_df["_dt"].dt.month.astype(int)

    written: list[Path] = []
    groups = sorted(etc_df.groupby(["_year", "_month"], sort=True))
    print("-" * 60)
    print(f"Writing {len(groups)} monthly vehicle-number file(s)…")

    for (year, month), group in groups:
        m_start, m_end = month_bounds(int(year), int(month))
        range_start, range_end = clip_month_range(
            m_start, m_end, overall_start, overall_end
        )
        if range_end < range_start:
            continue
        path = write_month_vehicle_file(
            group,
            plaza=entity_name,
            range_start=range_start,
            range_end=range_end,
            output_dir=OUTPUT_DIR,
        )
        written.append(path)

    print("=" * 60)
    print(f"Done — {len(written)} file(s) in {OUTPUT_DIR}")
    for path in written:
        print(f"  {path.name}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
