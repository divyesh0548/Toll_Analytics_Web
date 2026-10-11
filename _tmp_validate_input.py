"""One-off: validate Input Bassi Aug ETC/VRN against Plaza_db_update config."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "Plaza_db_update"))

from config.excel_config import (  # noqa: E402
    ETC_DATETIME_COLUMN_ALIASES,
    ETC_NPCI_CLASS_COLUMN_ALIASES,
    ETC_SETTLEMENT_COLUMN_ALIASES,
    LANE_COLUMN_ALIASES,
    MOP_COLUMN_ALIASES,
    VEHICLE_CLASS_COLUMN_ALIASES,
    VOLUME_REQUIRED_FIELDS,
)
from excel_common import (  # noqa: E402
    find_column_by_aliases,
    is_blank,
    is_excluded_vehicle_class,
    is_ignored_mop,
    read_excel_file,
    resolve_datetime_columns,
    try_normalize_lane,
    try_normalize_mop,
    try_normalize_vehicle_class,
)


def top_counts(d: dict, n: int = 40) -> dict:
    return dict(sorted(d.items(), key=lambda x: -x[1])[:n])


def inspect_vrn(path: Path) -> None:
    print("\n" + "=" * 70)
    print("VRN", path)
    try:
        df = read_excel_file(path, required_fields=VOLUME_REQUIRED_FIELDS)
    except Exception as exc:
        print("ETL read FAILED:", exc)
        raw = pd.read_excel(path, header=None, nrows=25, dtype=str)
        print(raw.head(20).to_string())
        return
    print("Columns:", list(df.columns))
    print("Rows:", len(df))
    try:
        dt = resolve_datetime_columns(df)
        print("Datetime OK:", dt)
    except Exception as exc:
        print("Datetime FAIL:", exc)
    vc = find_column_by_aliases(df, VEHICLE_CLASS_COLUMN_ALIASES)
    lane = find_column_by_aliases(df, LANE_COLUMN_ALIASES)
    mop = find_column_by_aliases(df, MOP_COLUMN_ALIASES)
    print("Mapped columns vc/lane/mop:", vc, lane, mop)
    missing = []
    if not vc:
        missing.append(("vehicle_class", VEHICLE_CLASS_COLUMN_ALIASES))
    if not lane:
        missing.append(("lane", LANE_COLUMN_ALIASES))
    if not mop:
        missing.append(("mop", MOP_COLUMN_ALIASES))
    if missing:
        print("MISSING COLUMN GROUPS:", missing)

    if vc:
        unmapped = {}
        for value in df[vc].astype(str):
            if is_blank(value) or is_excluded_vehicle_class(value):
                continue
            if try_normalize_vehicle_class(value) is None:
                key = value.strip()
                unmapped[key] = unmapped.get(key, 0) + 1
        print("Unmapped vehicle classes:", top_counts(unmapped))
    if mop:
        unmapped = {}
        for value in df[mop].astype(str):
            if is_blank(value) or is_ignored_mop(value):
                continue
            if try_normalize_mop(value) is None:
                key = value.strip()
                unmapped[key] = unmapped.get(key, 0) + 1
        print("Unmapped MOPs:", top_counts(unmapped))
    if lane:
        unmapped = {}
        for value in df[lane].astype(str):
            if is_blank(value):
                continue
            if try_normalize_lane(value) is None:
                key = value.strip()
                unmapped[key] = unmapped.get(key, 0) + 1
        print("Unmapped lanes:", top_counts(unmapped))


def inspect_etc(path: Path) -> None:
    print("\n" + "=" * 70)
    print("ETC", path)
    # Module4 uses required_fields for ETC — try volume reader without enforcing VRN fields
    try:
        df = read_excel_file(path, required_fields=("etc_datetime",))
    except Exception:
        try:
            df = read_excel_file(path, required_fields=VOLUME_REQUIRED_FIELDS)
        except Exception as exc:
            print("read_excel_file failed:", exc)
            # Manual header detect similar to keywords
            raw = pd.read_excel(path, header=None, nrows=40, dtype=str)
            print("Raw peek:")
            print(raw.head(20).to_string())
            # try first row as header heuristics: find row with Reader/Settlement
            best = None
            for i in range(min(30, len(raw))):
                cells = [str(c).strip() for c in raw.iloc[i].tolist() if str(c).strip() not in {"", "nan"}]
                joined = " | ".join(cells).lower()
                if "settlement" in joined or "reader read" in joined or "npci" in joined:
                    best = i
                    break
            if best is None:
                return
            df = pd.read_excel(path, header=best, dtype=str)
            print(f"Using header row {best}")
    print("Columns:", list(df.columns))
    print("Rows:", len(df))
    dt = find_column_by_aliases(df, ETC_DATETIME_COLUMN_ALIASES)
    npci = find_column_by_aliases(df, ETC_NPCI_CLASS_COLUMN_ALIASES)
    sett = find_column_by_aliases(df, ETC_SETTLEMENT_COLUMN_ALIASES)
    print("Mapped datetime/npci/settlement:", dt, npci, sett)
    missing = []
    if not dt:
        missing.append(("etc_datetime", ETC_DATETIME_COLUMN_ALIASES))
    if not npci:
        missing.append(("etc_npci", ETC_NPCI_CLASS_COLUMN_ALIASES))
    if not sett:
        missing.append(("etc_settlement", ETC_SETTLEMENT_COLUMN_ALIASES))
    if missing:
        print("MISSING COLUMN GROUPS:", missing)
        print("Actual columns for reference:", list(df.columns))
    if npci:
        unmapped = {}
        for value in df[npci].astype(str):
            if is_blank(value) or is_excluded_vehicle_class(value):
                continue
            if try_normalize_vehicle_class(value) is None:
                key = value.strip()
                unmapped[key] = unmapped.get(key, 0) + 1
        print("Unmapped NPCI classes:", top_counts(unmapped))


def main() -> None:
    inp = root / "Input"
    inspect_vrn(inp / "Bassi Aug VRN.xlsx")
    inspect_etc(inp / "Bassi Aug ETC.xlsx")


if __name__ == "__main__":
    main()
