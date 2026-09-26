"""
E4 — Pass merge → Trips taken (ETC if needed) → VRN TC Class → rates → Loss → DB.

1. Merge pass files. Stop if a Pass Type is not in config.json.
   Then drop empty vehicles and MP + Car/Jeep/Van rows.
2. If Trips taken missing: download/merge ETC for validity date range and count trips.
3. Download/merge VRN for the same date range; map TC Class onto pass vehicles.
   VRN date order is the entities list in vrn_merge_config.json
   (dd/mm/yyyy or mm/dd/yyyy). That list is not used for pass or ETC dates.
4. Map TC Class → index → single journey rate (PLAZA_RATES vs Apr26 onwards by
   validity end date). Total Charge = Trips × Rate; Loss = Total Charge − Issuance Fee
   (default fee from config if fee column/value missing). Missing other columns/keywords
   stop execution.
5. Sum Loss and Trips by Start-date month; upsert audit_exception_metrics (E04 / id 4).

Run:
  1. Set PASS_INPUT_FOLDER, ENTITY_NAME, PLAZA_IDENTIFIER below
  2. python E4_main.py
     or: python E4_main.py odhaki_paipkhar <plaza_uuid>
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from e4_db_update import (
    aggregate_monthly_loss_and_trips,
    parse_ordered_datetime_series,
    update_db_from_dataframe,
)
from plaza_rates import PLAZA_RATES, Plaza_Rates_Apr26_onwards

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
ETC_DOWNLOAD_MERGE_PATH = BASE_DIR / "etc-download-merge.py"
VRN_DOWNLOAD_MERGE_PATH = BASE_DIR / "vrn-download-merge.py"

# --- Runtime inputs (edit these; not in config.json) ---
PASS_INPUT_FOLDER = r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E4\Pass"
MERGED_OUTPUT_FILE = BASE_DIR / "output" / "merged_pass_files.xlsx"
# submissions.entity_name — used for ETC/VRN download and plaza rates lookup.
ENTITY_NAME = "bassi"
# plazas.plaza_identifier — required for audit_exception_metrics upsert.
PLAZA_IDENTIFIER = "94ecdec1-550c-4b4c-a94d-1df3b5fb4ac6"
EXCEPTION_TYPE_ID = 4
DB_DRY_RUN = False
SKIP_DB_UPDATE = False
# Result months outside this range are not written to the database.
EXPECTED_START = "2026-01-01"
EXPECTED_END = "2026-12-31"
EXCEL_EXTENSIONS = [".xlsx", ".xls", ".xlsm", ".csv"]


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def list_pass_files(folder: Path, extensions: list[str]) -> list[Path]:
    exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions}
    files = sorted(
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in exts and not p.name.startswith("~$")
    )
    return files


def _normalize_header_cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return " ".join(text.split())


def _normalize_header_key(value) -> str:
    return _normalize_header_cell(value).casefold()


def _normalize_value_key(value) -> str:
    """Casefold + collapse whitespace for value comparisons."""
    return _normalize_header_key(value)


def normalize_vehicle_number(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().upper()
    if text in {"", "NAN", "NONE", "NAT"}:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text)


def resolve_column(headers: list[str], aliases: list[str]) -> str | None:
    by_key = {_normalize_header_key(h): h for h in headers if _normalize_header_cell(h)}
    for alias in aliases or []:
        key = _normalize_header_key(alias)
        if key in by_key:
            return by_key[key]
    return None


def detect_header_row(
    df_raw: pd.DataFrame,
    keywords: list[str],
    *,
    scan_rows: int,
    min_matches: int,
) -> int:
    """
    Return 0-based row index of the header inside the first `scan_rows` rows.
    A row matches when at least `min_matches` keyword phrases appear as cells
    (case-insensitive, whitespace-normalized).
    """
    keyword_keys = {_normalize_header_key(k) for k in keywords if str(k).strip()}
    if not keyword_keys:
        raise ValueError("header_keywords is empty in config.json")

    limit = min(int(scan_rows), len(df_raw))
    best_idx = None
    best_score = -1

    for row_idx in range(limit):
        cells = {_normalize_header_key(v) for v in df_raw.iloc[row_idx].tolist()}
        cells.discard("")
        score = sum(1 for key in keyword_keys if key in cells)
        if score > best_score:
            best_score = score
            best_idx = row_idx

    if best_idx is None or best_score < int(min_matches):
        raise ValueError(
            f"Header row not detected (need >= {min_matches} keyword matches; "
            f"best score={best_score})."
        )
    return best_idx


def read_first_sheet_raw(path: Path) -> pd.DataFrame:
    """Load first sheet (or CSV) with no header so we can locate it ourselves."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    # sheet_name=0 → first sheet only
    return pd.read_excel(path, sheet_name=0, header=None, dtype=str)


def dataframe_from_header(
    df_raw: pd.DataFrame,
    header_idx: int,
) -> tuple[list[str], pd.DataFrame]:
    headers = [_normalize_header_cell(v) for v in df_raw.iloc[header_idx].tolist()]
    # Drop trailing empty header names that come from blank columns
    while headers and headers[-1] == "":
        headers.pop()
    if not any(headers):
        raise ValueError("Detected header row is empty")

    body = df_raw.iloc[header_idx + 1 :, : len(headers)].copy()
    body.columns = headers
    body = body.dropna(how="all").reset_index(drop=True)
    return headers, body


def header_signature(headers: list[str]) -> tuple[str, ...]:
    return tuple(_normalize_header_key(h) for h in headers)


def load_pass_file(
    path: Path,
    *,
    keywords: list[str],
    scan_rows: int,
    min_matches: int,
) -> tuple[list[str], pd.DataFrame]:
    print(f"Reading: {path.name}")
    df_raw = read_first_sheet_raw(path)
    if df_raw.empty:
        raise ValueError(f"File is empty: {path.name}")

    header_idx = detect_header_row(
        df_raw,
        keywords,
        scan_rows=scan_rows,
        min_matches=min_matches,
    )
    headers, df = dataframe_from_header(df_raw, header_idx)
    print(f"  Header at row {header_idx + 1} ({len(headers)} columns, {len(df)} data rows)")
    return headers, df


def drop_empty_vehicle_rows(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Remove rows whose vehicle / chassis number is blank after normalize."""
    headers = [str(c) for c in df.columns]
    aliases = config.get("pass_chassis_column_names") or []
    if not aliases:
        raise RuntimeError("pass_chassis_column_names is empty in config.json")
    veh_col = resolve_column(headers, aliases)
    if not veh_col:
        raise RuntimeError(
            "Vehicle/chassis column not found "
            f"(pass_chassis_column_names={aliases!r}). "
            f"Available: {list(df.columns)}"
        )

    keys = df[veh_col].map(normalize_vehicle_number)
    keep = keys.ne("")
    removed = int((~keep).sum())
    print(
        f"Empty vehicle filter on {veh_col!r}: removed {removed}, kept {int(keep.sum())}"
    )
    return df.loc[keep].reset_index(drop=True)


def drop_mp_car_jeep_van_rows(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Remove rows only when BOTH are true:
      Pass Type ∈ exclude pass-type values (e.g. MP)
      AND vehicle class ∈ Car/Jeep/Van (aliases)
    """
    headers = [str(c) for c in df.columns]
    rule = config.get("exclude_mp_car_jeep_van")
    if not isinstance(rule, dict) or not rule:
        raise RuntimeError("exclude_mp_car_jeep_van is missing or empty in config.json")

    pass_aliases = config.get("pass_type_column_names") or []
    class_aliases = config.get("mapper_vehicle_class_column_names") or []
    if not pass_aliases:
        raise RuntimeError("pass_type_column_names is empty in config.json")
    if not class_aliases:
        raise RuntimeError("mapper_vehicle_class_column_names is empty in config.json")

    pass_col = resolve_column(headers, pass_aliases)
    class_col = resolve_column(headers, class_aliases)

    if not pass_col or not class_col:
        missing = []
        if not pass_col:
            missing.append(f"pass_type_column_names={pass_aliases!r}")
        if not class_col:
            missing.append(f"mapper_vehicle_class_column_names={class_aliases!r}")
        raise RuntimeError(
            "Could not resolve columns for MP+Car/Jeep/Van filter: "
            + ", ".join(missing)
            + f". Available: {list(df.columns)}"
        )

    pass_values = {
        _normalize_value_key(v)
        for v in (rule.get("pass_type_values") or [])
        if str(v).strip()
    }
    class_values = {
        _normalize_value_key(v)
        for v in (rule.get("vehicle_class_values") or [])
        if str(v).strip()
    }
    if not pass_values or not class_values:
        raise RuntimeError(
            "exclude_mp_car_jeep_van pass_type_values / vehicle_class_values "
            "must be non-empty in config.json"
        )

    pass_keys = df[pass_col].map(_normalize_value_key)
    class_keys = df[class_col].map(_normalize_value_key)
    drop_mask = pass_keys.isin(pass_values) & class_keys.isin(class_values)

    removed = int(drop_mask.sum())
    kept = len(df) - removed
    print(
        f"Filter MP + Car/Jeep/Van: using columns "
        f"{pass_col!r} + {class_col!r} — removed {removed}, kept {kept}"
    )
    return df.loc[~drop_mask].reset_index(drop=True)


def known_pass_type_keys(config: dict) -> set[str]:
    """Pass types the program is allowed to see. Unknown values stop the run."""
    names: list = []
    names.extend(config.get("mp_pass_type_values") or [])
    names.extend(config.get("lt_pass_type_values") or [])
    rule = config.get("exclude_mp_car_jeep_van") or {}
    if isinstance(rule, dict):
        names.extend(rule.get("pass_type_values") or [])
    keys = {_normalize_value_key(name) for name in names if str(name).strip()}
    if not keys:
        raise RuntimeError(
            "mp_pass_type_values and lt_pass_type_values are empty in config.json"
        )
    return keys


def assert_known_pass_types(df: pd.DataFrame, config: dict) -> None:
    headers = [str(c) for c in df.columns]
    aliases = config.get("pass_type_column_names") or []
    if not aliases:
        raise RuntimeError("pass_type_column_names is empty in config.json")
    pass_col = resolve_column(headers, aliases)
    if not pass_col:
        raise RuntimeError(
            "Pass Type column not found "
            f"(pass_type_column_names={aliases!r}). Available: {list(df.columns)}"
        )

    known = known_pass_type_keys(config)
    unknown: dict[str, str] = {}
    for raw in df[pass_col].tolist():
        key = _normalize_value_key(raw)
        if key in known:
            continue
        label = _normalize_header_cell(raw) or "blank"
        unknown.setdefault(key, label)

    if not unknown:
        print(f"Pass Type values are all defined in config.json ({pass_col!r}).")
        return

    listed = ", ".join(repr(label) for label in sorted(unknown.values(), key=str.casefold))
    raise RuntimeError(
        f"Pass Type value(s) not defined in config.json: {listed}. "
        "Add each one to mp_pass_type_values or lt_pass_type_values. Stopping."
    )


def merge_pass_folder(config: dict) -> tuple[Path, pd.DataFrame]:
    folder_raw = str(PASS_INPUT_FOLDER or "").strip()
    if not folder_raw:
        raise RuntimeError("Set PASS_INPUT_FOLDER at the top of E4_main.py")

    folder = Path(folder_raw)
    if not folder.is_dir():
        raise FileNotFoundError(f"Pass input folder not found: {folder}")

    files = list_pass_files(folder, EXCEL_EXTENSIONS)
    if not files:
        raise FileNotFoundError(f"No Pass files found in: {folder}")

    keywords = config.get("header_keywords") or []
    if not keywords:
        raise RuntimeError("header_keywords is empty in config.json")
    scan_rows = int(config.get("header_scan_rows") or 25)
    min_matches = int(config.get("min_header_matches") or 3)

    print(f"Folder: {folder}")
    print(f"Files found: {len(files)}")
    print("=" * 60)

    reference_headers: list[str] | None = None
    reference_signature: tuple[str, ...] | None = None
    reference_file: str | None = None
    frames: list[pd.DataFrame] = []

    for path in files:
        headers, df = load_pass_file(
            path,
            keywords=keywords,
            scan_rows=scan_rows,
            min_matches=min_matches,
        )
        signature = header_signature(headers)

        if reference_signature is None:
            reference_headers = headers
            reference_signature = signature
            reference_file = path.name
        elif signature != reference_signature:
            raise RuntimeError(
                "Header mismatch — all Pass files must share the same header row.\n"
                f"  Reference file : {reference_file}\n"
                f"  Reference cols : {reference_headers}\n"
                f"  Current file   : {path.name}\n"
                f"  Current cols   : {headers}\n"
                "Execution stopped."
            )

        # Force identical column names (preserve first file's display casing).
        df = df.copy()
        df.columns = list(reference_headers)
        df["__source_file"] = path.name
        frames.append(df)

    merged = pd.concat(frames, ignore_index=True)
    print("=" * 60)
    print(f"Merged rows (before filter): {len(merged)} from {len(frames)} file(s)")

    assert_known_pass_types(merged, config)
    merged = drop_empty_vehicle_rows(merged, config)
    merged = drop_mp_car_jeep_van_rows(merged, config)
    print(f"Merged rows (after filters): {len(merged)}")

    output_path = Path(MERGED_OUTPUT_FILE)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_excel(output_path, index=False)
    print(f"Wrote: {output_path}")
    return output_path, merged


def resolve_entity_name() -> str:
    if len(sys.argv) >= 2 and str(sys.argv[1]).strip():
        return str(sys.argv[1]).strip()
    name = str(ENTITY_NAME or "").strip()
    if name:
        return name
    name = input("Enter entity_name (submissions.entity_name): ").strip()
    if not name:
        raise RuntimeError("entity_name is required for ETC/VRN download and rates.")
    return name


def resolve_plaza_identifier() -> str:
    if len(sys.argv) >= 3 and str(sys.argv[2]).strip():
        return str(sys.argv[2]).strip()
    plaza_id = str(PLAZA_IDENTIFIER or "").strip()
    if plaza_id:
        return plaza_id
    plaza_id = input("Enter plaza_identifier (plazas.plaza_identifier UUID): ").strip()
    if not plaza_id:
        raise RuntimeError("plaza_identifier is required for audit_exception_metrics.")
    return plaza_id


def pass_date_order(config: dict, entity_name: str) -> str:
    """Pass files only. Example 18-03-2026 00:00:00 is dd/mm/yyyy."""
    allowed = {"dd/mm/yyyy", "mm/dd/yyyy", "dd-mmm-yyyy"}
    key = str(entity_name or "").strip().casefold()
    for row in config.get("entities") or []:
        name = str(row.get("entity_name") or "").strip().casefold()
        if name != key:
            continue
        order = str(row.get("date_format") or "").strip().casefold()
        if order not in allowed:
            raise RuntimeError(
                f"Set date_format for {entity_name!r} in config.json entities "
                "to dd/mm/yyyy, mm/dd/yyyy, or dd-mmm-yyyy. "
                "18-03-2026 00:00:00 is dd/mm/yyyy."
            )
        return order
    raise RuntimeError(
        f"Add {entity_name!r} to the entities list in config.json "
        "and set date_format for pass files."
    )


def parse_datetime_series(series: pd.Series, date_order: str | None = None) -> pd.Series:
    """Pass dates use date_order. Other files keep pandas' own parse."""
    text = series.astype(str).str.strip()
    text = text.replace({"": pd.NA, "nan": pd.NA, "NaT": pd.NA, "None": pd.NA})
    if date_order:
        return parse_ordered_datetime_series(text, date_order)
    parsed = pd.to_datetime(text, errors="coerce")
    return parsed


def validity_date_range(df: pd.DataFrame, config: dict) -> tuple[date, date]:
    headers = [str(c) for c in df.columns]
    start_aliases = config.get("pass_start_date_column_names") or []
    end_aliases = config.get("pass_end_date_column_names") or []
    if not start_aliases:
        raise RuntimeError("pass_start_date_column_names is empty in config.json")
    if not end_aliases:
        raise RuntimeError("pass_end_date_column_names is empty in config.json")

    start_col = resolve_column(headers, start_aliases)
    end_col = resolve_column(headers, end_aliases)
    if not start_col or not end_col:
        missing = []
        if not start_col:
            missing.append(f"pass_start_date_column_names={start_aliases!r}")
        if not end_col:
            missing.append(f"pass_end_date_column_names={end_aliases!r}")
        raise RuntimeError(
            "Could not resolve validity date columns: "
            + ", ".join(missing)
            + f". Available: {list(df.columns)}"
        )

    order = str(config.get("pass_date_order") or "").strip()
    start_parsed = parse_datetime_series(df[start_col], order or None)
    end_parsed = parse_datetime_series(df[end_col], order or None)
    if start_parsed.isna().all():
        raise RuntimeError(f"No valid datetimes in start column {start_col!r}")
    if end_parsed.isna().all():
        raise RuntimeError(f"No valid datetimes in end column {end_col!r}")

    earliest = start_parsed.min()
    latest = end_parsed.max()
    start_d = earliest.date() if hasattr(earliest, "date") else pd.Timestamp(earliest).date()
    end_d = latest.date() if hasattr(latest, "date") else pd.Timestamp(latest).date()
    if end_d < start_d:
        raise RuntimeError(
            f"Invalid validity range: earliest start {start_d} is after latest end {end_d}"
        )

    print(
        f"Validity range from columns {start_col!r} / {end_col!r}: "
        f"{start_d.isoformat()} → {end_d.isoformat()}"
    )
    return start_d, end_d


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


def load_vrn_download_merge_module():
    path = VRN_DOWNLOAD_MERGE_PATH
    if not path.is_file():
        raise FileNotFoundError(f"VRN download script not found: {path}")
    spec = importlib.util.spec_from_file_location("e4_vrn_download_merge", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize_tc_class_key(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    if text in {"", "nan", "none", "nat"}:
        return ""
    return text


def build_tc_class_skip_set(config: dict) -> set[str]:
    raw = config.get("tc_class_skip_list") or []
    skip: set[str] = set()
    for name in raw:
        key = normalize_tc_class_key(name)
        if key:
            skip.add(key)
    return skip


def build_tc_class_index_lookup(config: dict) -> dict[str, int]:
    """
    Build name → index from tc_class_index_map.

    Expected shape (preferred):
      { "1": ["car", "carjeep"], "2": ["lcv", ...], ... }

    Also accepts legacy flat shape: { "car": 1, "lcv": 2, ... }
    """
    raw = config.get("tc_class_index_map") or {}
    lookup: dict[str, int] = {}

    # Preferred: index → list of names
    list_style = any(isinstance(v, list) for v in raw.values())
    if list_style:
        for idx_raw, names in raw.items():
            try:
                idx = int(idx_raw)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"Invalid tc_class_index_map key {idx_raw!r} — expected index number"
                ) from exc
            if not isinstance(names, list):
                raise RuntimeError(
                    f"tc_class_index_map[{idx_raw!r}] must be a list of class names"
                )
            for name in names:
                key = normalize_tc_class_key(name)
                if not key:
                    continue
                lookup[key] = idx
    else:
        for name, idx in raw.items():
            key = normalize_tc_class_key(name)
            if not key:
                continue
            lookup[key] = int(idx)

    if not lookup:
        raise RuntimeError("tc_class_index_map is empty in config.json")
    return lookup


def build_vrn_tc_class_lookup(vrn_path: Path) -> dict[str, str]:
    """Map normalized vehicle → first non-empty TC Class from merged VRN CSV."""
    print(f"Loading merged VRN: {vrn_path}")
    vrn_df = pd.read_csv(vrn_path, dtype=str, keep_default_na=False)
    if "vehicle_reg_no" not in vrn_df.columns or "tc_class" not in vrn_df.columns:
        raise RuntimeError(
            "Merged VRN file must contain columns vehicle_reg_no and tc_class"
        )

    lookup: dict[str, str] = {}
    for veh_raw, tc_raw in zip(
        vrn_df["vehicle_reg_no"].tolist(),
        vrn_df["tc_class"].tolist(),
    ):
        veh = normalize_vehicle_number(veh_raw)
        tc = str(tc_raw).strip() if tc_raw is not None else ""
        if not veh or not tc or tc.lower() in {"nan", "none", "nat"}:
            continue
        if veh not in lookup:
            lookup[veh] = tc
    print(f"  Distinct vehicles with TC Class in VRN: {len(lookup)}")
    return lookup


def attach_tc_class_from_vrn(
    pass_df: pd.DataFrame,
    vrn_lookup: dict[str, str],
    config: dict,
) -> pd.DataFrame:
    headers = [str(c) for c in pass_df.columns]
    veh_col = resolve_column(headers, config.get("pass_chassis_column_names") or [])
    if not veh_col:
        raise RuntimeError(
            "Cannot attach TC Class — pass chassis column not found "
            "(pass_chassis_column_names)"
        )

    out_col = str(config.get("tc_class_output_column") or "TC Class").strip() or "TC Class"
    vehs = pass_df[veh_col].map(normalize_vehicle_number)
    tc_values = [vrn_lookup.get(v, "") for v in vehs.tolist()]

    result = pass_df.copy()
    result[out_col] = tc_values
    matched = sum(1 for v in tc_values if v)
    print(
        f"TC Class attached via VRN on {veh_col!r} → {out_col!r}: "
        f"{matched}/{len(result)} rows matched"
    )
    return result


def resolve_tc_class_index(
    tc_value: str,
    lookup: dict[str, int],
    *,
    skip_set: set[str] | None = None,
) -> int | None:
    key = normalize_tc_class_key(tc_value)
    if not key:
        return None
    if skip_set and key in skip_set:
        return None
    if key not in lookup:
        raise RuntimeError(
            f"Unknown TC Class {tc_value!r} (normalized {key!r}) — "
            "not present in tc_class_index_map. Stopping."
        )
    return lookup[key]


def parse_rate_cutover_date(config: dict) -> date:
    raw = str(config.get("rate_cutover_date") or "2026-05-01").strip()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid rate_cutover_date in config: {raw!r}") from exc


def select_plaza_rates_book(end_d: date, cutover: date) -> dict:
    """End date on/before day before cutover → PLAZA_RATES; else Apr26 onwards."""
    if end_d < cutover:
        return PLAZA_RATES
    return Plaza_Rates_Apr26_onwards


def lookup_single_rate(
    entity_name: str,
    rates_book: dict,
    class_index: int,
) -> float:
    key = str(entity_name or "").strip()
    plaza = rates_book.get(key)
    if plaza is None:
        plaza = rates_book.get(key.lower())
    if plaza is None:
        raise RuntimeError(
            f"Entity {entity_name!r} not found in plaza rates "
            f"({ 'PLAZA_RATES' if rates_book is PLAZA_RATES else 'Plaza_Rates_Apr26_onwards' })"
        )
    single = plaza.get("single") if isinstance(plaza, dict) else None
    if not isinstance(single, dict):
        raise RuntimeError(f"No 'single' rates for entity {entity_name!r}")
    if class_index not in single:
        raise RuntimeError(
            f"No single rate for class index {class_index} on entity {entity_name!r}"
        )
    return float(single[class_index])


def _to_float_or_none(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "")
    if text == "" or text.lower() in {"nan", "none", "nat"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def compute_total_charge_and_loss(
    pass_df: pd.DataFrame,
    config: dict,
    entity_name: str,
) -> pd.DataFrame:
    headers = [str(c) for c in pass_df.columns]
    tc_aliases = [
        str(config.get("tc_class_output_column") or "").strip(),
        "TC Class",
        "Tc Class",
    ]
    tc_aliases = [a for a in tc_aliases if a]
    trips_aliases = config.get("trips_taken_column_names") or []
    end_aliases = config.get("pass_end_date_column_names") or []
    fee_aliases = config.get("issuance_fee_column_names") or []

    if not trips_aliases:
        raise RuntimeError("trips_taken_column_names is empty in config.json")
    if not end_aliases:
        raise RuntimeError("pass_end_date_column_names is empty in config.json")

    tc_col = resolve_column(headers, tc_aliases)
    trips_col = resolve_column(headers, trips_aliases)
    end_col = resolve_column(headers, end_aliases)
    fee_col = resolve_column(headers, fee_aliases) if fee_aliases else None

    if not tc_col:
        raise RuntimeError(
            f"TC Class column not found (tried {tc_aliases!r}). "
            f"Available: {list(pass_df.columns)}"
        )
    if not trips_col:
        raise RuntimeError(
            f"Trips taken column not found (trips_taken_column_names={trips_aliases!r}). "
            f"Available: {list(pass_df.columns)}"
        )
    if not end_col:
        raise RuntimeError(
            "Validity end date column not found "
            f"(pass_end_date_column_names={end_aliases!r}). "
            f"Available: {list(pass_df.columns)}"
        )

    charge_col = (
        str(config.get("total_charge_output_column") or "Total Charge").strip()
        or "Total Charge"
    )
    loss_col = str(config.get("loss_output_column") or "Loss").strip() or "Loss"
    default_fee = float(config.get("default_issuance_fee", 360))
    cutover = parse_rate_cutover_date(config)
    index_lookup = build_tc_class_index_lookup(config)
    skip_set = build_tc_class_skip_set(config)
    if skip_set:
        print(f"TC Class skip list: {sorted(skip_set)}")

    ends = parse_datetime_series(
        pass_df[end_col], str(config.get("pass_date_order") or "") or None
    )
    trips = [_to_float_or_none(v) for v in pass_df[trips_col].tolist()]
    tc_values = pass_df[tc_col].tolist()
    fees = (
        [_to_float_or_none(v) for v in pass_df[fee_col].tolist()]
        if fee_col
        else [None] * len(pass_df)
    )
    if fee_col:
        print(f"Issuance fee column: {fee_col!r}")
    else:
        print(f"Issuance fee column not found — using default {default_fee}")

    charges: list[float | None] = []
    losses: list[float | None] = []
    rated = 0
    skipped = 0

    for tc_raw, trip_raw, end_ts, fee_raw in zip(tc_values, trips, ends.tolist(), fees):
        tc_key = normalize_tc_class_key(tc_raw)
        if tc_key and tc_key in skip_set:
            charges.append(None)
            losses.append(None)
            skipped += 1
            continue

        # Validate / map every non-empty TC Class (raises on unknown).
        class_index = resolve_tc_class_index(tc_raw, index_lookup, skip_set=skip_set)
        if class_index is None or trip_raw is None or end_ts is None or pd.isna(end_ts):
            charges.append(None)
            losses.append(None)
            continue

        end_d = pd.Timestamp(end_ts).date()
        rates_book = select_plaza_rates_book(end_d, cutover)
        rate = lookup_single_rate(entity_name, rates_book, class_index)
        total = float(trip_raw) * rate
        fee = default_fee if fee_raw is None else float(fee_raw)
        charges.append(total)
        losses.append(total - fee)
        rated += 1

    result = pass_df.copy()
    result[charge_col] = charges
    result[loss_col] = losses
    print(
        f"Rates applied for entity {entity_name!r} "
        f"(cutover {cutover.isoformat()}): "
        f"{rated}/{len(result)} rows → {charge_col!r} / {loss_col!r}"
        + (f" (skipped TC Class: {skipped})" if skipped else "")
    )
    return result


def run_vrn_tc_rates_loss(
    merged: pd.DataFrame,
    config: dict,
    output_path: Path,
) -> pd.DataFrame:
    start_d, end_d = validity_date_range(merged, config)
    entity_name = resolve_entity_name()
    print(f"Starting VRN download/merge for entity_name={entity_name!r}")

    vrn_mod = load_vrn_download_merge_module()
    vrn_path = vrn_mod.run_vrn_download_merge(
        entity_name,
        start_d.isoformat(),
        end_d.isoformat(),
        delete_downloads=False,
    )
    if vrn_path is None:
        raise RuntimeError("VRN download finished without a merged file path.")
    print(f"VRN merge complete: {vrn_path}")

    vrn_lookup = build_vrn_tc_class_lookup(Path(vrn_path))
    with_tc = attach_tc_class_from_vrn(merged, vrn_lookup, config)
    final = compute_total_charge_and_loss(with_tc, config, entity_name)
    save_merged_pass(final, output_path)
    return final


def _to_ordinal_date(ts) -> int | None:
    if ts is None or pd.isna(ts):
        return None
    stamp = pd.Timestamp(ts)
    return int(stamp.toordinal())


def build_etc_vehicle_date_index(etc_df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Map normalized vehicle → sorted array of read calendar-day ordinals."""
    work = etc_df.copy()
    if "vehicle_reg_no" not in work.columns or "read_datetime" not in work.columns:
        raise RuntimeError(
            "Merged ETC file must contain columns vehicle_reg_no and read_datetime"
        )

    work["_veh"] = work["vehicle_reg_no"].map(normalize_vehicle_number)
    work["_dt"] = parse_datetime_series(work["read_datetime"])
    work = work.loc[work["_veh"].ne("") & work["_dt"].notna(), ["_veh", "_dt"]]
    if work.empty:
        return {}

    work["_day"] = work["_dt"].map(_to_ordinal_date)
    work = work.dropna(subset=["_day"])
    index: dict[str, np.ndarray] = {}
    for veh, group in work.groupby("_veh", sort=False):
        days = np.sort(group["_day"].to_numpy(dtype=np.int64))
        index[str(veh)] = days
    return index


def count_trips_for_range(
    day_ordinals: np.ndarray | None,
    start_ts,
    end_ts,
) -> int:
    if day_ordinals is None or len(day_ordinals) == 0:
        return 0
    start_ord = _to_ordinal_date(start_ts)
    end_ord = _to_ordinal_date(end_ts)
    if start_ord is None or end_ord is None:
        return 0
    if end_ord < start_ord:
        return 0
    left = int(np.searchsorted(day_ordinals, start_ord, side="left"))
    right = int(np.searchsorted(day_ordinals, end_ord, side="right"))
    return max(0, right - left)


def fill_trips_taken_from_etc(
    pass_df: pd.DataFrame,
    etc_path: Path,
    config: dict,
) -> pd.DataFrame:
    headers = [str(c) for c in pass_df.columns]
    veh_col = resolve_column(headers, config.get("pass_chassis_column_names") or [])
    start_col = resolve_column(headers, config.get("pass_start_date_column_names") or [])
    end_col = resolve_column(headers, config.get("pass_end_date_column_names") or [])
    if not veh_col or not start_col or not end_col:
        missing = []
        if not veh_col:
            missing.append("pass_chassis_column_names")
        if not start_col:
            missing.append("pass_start_date_column_names")
        if not end_col:
            missing.append("pass_end_date_column_names")
        raise RuntimeError(
            "Cannot compute Trips taken — missing pass columns: " + ", ".join(missing)
        )

    out_col = str(config.get("trips_taken_output_column") or "Trips taken").strip()
    if not out_col:
        out_col = "Trips taken"

    print(f"Loading merged ETC: {etc_path}")
    etc_df = pd.read_csv(etc_path, dtype=str, keep_default_na=False)
    print(f"  ETC rows: {len(etc_df)}")
    etc_index = build_etc_vehicle_date_index(etc_df)
    print(f"  Distinct vehicles in ETC: {len(etc_index)}")

    order = str(config.get("pass_date_order") or "") or None
    starts = parse_datetime_series(pass_df[start_col], order)
    ends = parse_datetime_series(pass_df[end_col], order)
    vehs = pass_df[veh_col].map(normalize_vehicle_number)

    counts: list[int] = []
    for veh, start_ts, end_ts in zip(vehs.tolist(), starts.tolist(), ends.tolist()):
        counts.append(count_trips_for_range(etc_index.get(veh), start_ts, end_ts))

    result = pass_df.copy()
    result[out_col] = counts
    matched = sum(1 for c in counts if c > 0)
    print(
        f"Trips taken filled via ETC match on {veh_col!r} "
        f"within {start_col!r}–{end_col!r}: "
        f"{matched}/{len(result)} rows have count > 0 "
        f"(total trip rows counted: {sum(counts)})"
    )
    return result


def save_merged_pass(df: pd.DataFrame, output_path: Path) -> Path:
    output_path = Path(output_path)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False)
    print(f"Wrote: {output_path}")
    return output_path


def maybe_run_etc_download(merged: pd.DataFrame, config: dict, output_path: Path) -> pd.DataFrame:
    headers = [str(c) for c in merged.columns]
    trips_col = resolve_column(headers, config.get("trips_taken_column_names") or [])
    if trips_col:
        print(
            f"Trips taken column found ({trips_col!r}) — "
            "skipping ETC download/merge and trip counting."
        )
        return merged

    print("Trips taken column not found — deriving ETC date range from validity dates.")
    start_d, end_d = validity_date_range(merged, config)
    entity_name = resolve_entity_name()
    print(f"Starting ETC download/merge for entity_name={entity_name!r}")

    etc_mod = load_etc_download_merge_module()
    etc_path = etc_mod.run_etc_download_merge(
        entity_name,
        start_d.isoformat(),
        end_d.isoformat(),
    )
    if etc_path is None:
        raise RuntimeError("ETC download finished without a merged file path.")
    print(f"ETC merge complete: {etc_path}")

    updated = fill_trips_taken_from_etc(merged, Path(etc_path), config)
    save_merged_pass(updated, output_path)
    return updated


def months_outside_expected(rows: list[dict], start: date, end: date) -> list[str]:
    low = (start.year, start.month)
    high = (end.year, end.month)
    outside: list[str] = []
    for row in rows:
        key = (int(row["year"]), int(row["month"]))
        if key < low or key > high:
            outside.append(f"{key[0]}-{key[1]:02d}")
    return outside


def main() -> int:
    config = load_config()
    entity_name = resolve_entity_name()
    config["pass_date_order"] = pass_date_order(config, entity_name)
    print(f"Pass date order for {entity_name}: {config['pass_date_order']}")
    output_path, merged = merge_pass_folder(config)
    merged = maybe_run_etc_download(merged, config, output_path)
    merged = run_vrn_tc_rates_loss(merged, config, output_path)

    if SKIP_DB_UPDATE:
        print("SKIP_DB_UPDATE=True — audit_exception_metrics not updated.")
        return 0

    entity_name = resolve_entity_name()
    start_raw = str(EXPECTED_START or "").strip()
    end_raw = str(EXPECTED_END or "").strip()
    monthly = aggregate_monthly_loss_and_trips(
        merged,
        start_date_aliases=config.get("pass_start_date_column_names") or None,
        loss_aliases=[config.get("loss_output_column") or "Loss", "Loss"],
        trips_aliases=config.get("trips_taken_column_names") or None,
        date_order=str(config.get("pass_date_order") or "") or None,
        only_nonzero_trips=True,
    )
    print("-" * 60)
    print(f"Months with trips for {entity_name}: {len(monthly)}")
    print("Months with 0 trips are not written to the database.")
    for row in monthly:
        print(
            f"  {int(row['year'])}-{int(row['month']):02d}: "
            f"trips={int(row['total_count']):,}, loss={row['total_amount']}"
        )
    if not monthly:
        print("No months with trips. DB not updated.")
        return 0
    if not start_raw or not end_raw:
        print(
            "Set EXPECTED_START and EXPECTED_END (YYYY-MM-DD) at the top of "
            "E4_main.py. DB not updated."
        )
        return 0
    try:
        expected_start = date.fromisoformat(start_raw)
        expected_end = date.fromisoformat(end_raw)
    except ValueError as exc:
        raise RuntimeError(
            "EXPECTED_START and EXPECTED_END must be YYYY-MM-DD."
        ) from exc
    if expected_end < expected_start:
        raise RuntimeError(
            f"EXPECTED_END {expected_end.isoformat()} is before "
            f"EXPECTED_START {expected_start.isoformat()}."
        )
    outside = months_outside_expected(monthly, expected_start, expected_end)
    if outside:
        print(
            f"Months outside {expected_start.isoformat()} → {expected_end.isoformat()}: "
            f"{', '.join(outside)}. DB not updated."
        )
        return 0

    plaza_identifier = resolve_plaza_identifier()
    print("-" * 60)
    print("Updating audit_exception_metrics (exception_type_id=4)…")
    update_db_from_dataframe(
        merged,
        plaza_identifier,
        exception_type_id=int(EXCEPTION_TYPE_ID),
        dry_run=bool(DB_DRY_RUN),
        start_date_aliases=config.get("pass_start_date_column_names") or None,
        loss_aliases=[config.get("loss_output_column") or "Loss", "Loss"],
        trips_aliases=config.get("trips_taken_column_names") or None,
        date_order=str(config.get("pass_date_order") or "") or None,
        only_nonzero_trips=True,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
