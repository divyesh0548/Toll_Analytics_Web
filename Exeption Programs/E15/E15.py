"""
E15 — From-To plaza merge + Applicable Rate + DB metrics.

1) Read From-plaza exempt Excel files; take min/max Date & Time
2) Download/merge To-plaza VRN from submissions for TO_PLAZA_ENTITY_NAME
3) Merge on vehicle + SIDE; keep MATCH=Yes and PAYMENT METHOD != EXEMPT
4) Applicable Rate from TC Class + Journey Type via plaza_rates
5) Optionally upsert audit_exception_metrics (exception id 15) by Date & Time month

Keywords / maps: E15_config.json
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv

from e15_db_update import update_db_from_dataframe

BASE_DIR = Path(__file__).resolve().parent
E4_DIR = BASE_DIR.parent / "E4"
E10_DIR = BASE_DIR.parent / "E10"
WEBSITE_ENV = BASE_DIR.parent.parent / "Website" / "backend" / ".env"
CONFIG_PATH = BASE_DIR / "E15_config.json"
VRN_DOWNLOAD_MERGE_PATH = E4_DIR / "vrn-download-merge.py"
VEHICLE_CLASS_PATH = E10_DIR / "vehicle-class.py"

# Plaza rates (E4)
if str(E4_DIR) not in sys.path:
    sys.path.insert(0, str(E4_DIR))
from plaza_rates import PLAZA_RATES, Plaza_Rates_Apr26_onwards  # noqa: E402


def _load_vehicle_class_module():
    """Load E10/vehicle-class.py (hyphenated filename)."""
    path = VEHICLE_CLASS_PATH
    if not path.is_file():
        raise FileNotFoundError(f"vehicle-class.py not found: {path}")
    spec = importlib.util.spec_from_file_location("e10_vehicle_class", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_VEHICLE_CLASS_MOD = _load_vehicle_class_module()
WEIGHT_RANGE_INDEXES = _VEHICLE_CLASS_MOD.WEIGHT_RANGE_INDEXES

# --- Runtime inputs (edit these; not in config) ---
FROM_PLAZA_FOLDER = r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E15\from plaza"
TO_PLAZA_ENTITY_NAME = "khawasa"  # submissions.entity_name for To-plaza VRN
OUTPUT_FOLDER = r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E15\output"
FALLBACK_FROM_PLAZA_FOLDER = BASE_DIR / "from_plaza_input"
FALLBACK_OUTPUT_FOLDER = BASE_DIR / "output"
VRN_DOWNLOAD_FOLDER = BASE_DIR / "vrn_downloads"
INDIVIDUAL_OUTPUT_PREFIX = "from_to"
COMBINED_OUTPUT_FILENAME = "from_to_combined.xlsx"
# plazas.plaza_identifier — required when UPDATE_DB is True
PLAZA_IDENTIFIER = "d55c2122-117c-45be-8554-7ea76730932b"
EXCEPTION_TYPE_ID = 15
UPDATE_DB = True
DB_DRY_RUN = False

_CONFIG: dict | None = None


def load_config(path: Path = CONFIG_PATH) -> dict:
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    if not path.is_file():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        _CONFIG = json.load(fh)
    return _CONFIG


def load_env() -> None:
    """Load Website/backend/.env and map names used by E4 VRN download."""
    if not WEBSITE_ENV.is_file():
        raise FileNotFoundError(f"Env file not found: {WEBSITE_ENV}")
    load_dotenv(WEBSITE_ENV, override=True)
    source_db = os.getenv("Source_DB_NAME", "").strip()
    if source_db:
        os.environ["DB_NAME"] = source_db
    table = (
        os.getenv("exceptions_Table_NAME", "").strip()
        or os.getenv("Table_NAME", "").strip()
        or "submissions"
    )
    os.environ["Table_NAME"] = table


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name} (in {WEBSITE_ENV})")
    return value


def _norm_header_token(value) -> str:
    return (
        str(value)
        .upper()
        .replace(" ", "")
        .replace("_", "")
        .replace(".", "")
    )


def resolve_entity_name() -> str:
    if len(sys.argv) >= 2 and str(sys.argv[1]).strip():
        return str(sys.argv[1]).strip()
    name = str(TO_PLAZA_ENTITY_NAME or "").strip()
    if name:
        return name
    name = input("Enter To-plaza entity_name (submissions.entity_name): ").strip()
    if not name:
        raise RuntimeError("TO_PLAZA_ENTITY_NAME is required.")
    return name


def resolve_plaza_identifier() -> str:
    """plazas.plaza_identifier — CLI argv[2], then PLAZA_IDENTIFIER, then prompt."""
    if len(sys.argv) >= 3 and str(sys.argv[2]).strip():
        return str(sys.argv[2]).strip()
    value = str(PLAZA_IDENTIFIER or "").strip()
    if value:
        return value
    value = input("Enter plaza_identifier (plazas.plaza_identifier): ").strip()
    if not value:
        raise RuntimeError("PLAZA_IDENTIFIER is required when UPDATE_DB is True.")
    return value


# =========================================================
# HELPERS
# =========================================================


def read_excel_smart(file_path, config: dict | None = None):
    config = config or load_config()
    header_keywords = {
        _norm_header_token(k) for k in (config.get("header_keywords") or [])
    }
    scan_rows = int(config.get("header_scan_rows") or 25)
    min_matches = int(config.get("min_header_matches") or 2)

    try:
        df_sample = pd.read_excel(file_path, header=None, nrows=scan_rows)
        detected_row = 0
        for idx, row in df_sample.iterrows():
            row_str_cells = [_norm_header_token(x) for x in row.dropna()]
            matches = sum(
                1
                for cell in row_str_cells
                if any(kw == cell or kw in cell for kw in header_keywords)
            )
            if matches >= min_matches:
                detected_row = idx
                break
        df = pd.read_excel(file_path, skiprows=detected_row)
    except Exception:
        df = pd.read_excel(file_path)

    df.columns = [str(c).strip() for c in df.columns]
    return df


def read_table_smart(file_path, config: dict | None = None):
    """Excel with header detect, or CSV with headers already promoted (merged VRN)."""
    path = Path(file_path)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        df.columns = [str(c).strip() for c in df.columns]
        return df
    return read_excel_smart(path, config)


def robust_parse_time(series, config: dict | None = None):
    config = config or load_config()
    formats = list(config.get("time_formats") or [])
    null_vals = {
        str(v).strip().lower()
        for v in (config.get("null_time_values") or [])
    }

    def parse_single_val(val):
        if pd.isna(val):
            return pd.NaT
        if isinstance(val, pd.Timestamp):
            return val
        if isinstance(val, type(pd.NaT)):
            return pd.NaT
        if hasattr(val, "hour") and hasattr(val, "minute"):
            return pd.Timestamp(
                year=2000,
                month=1,
                day=1,
                hour=val.hour,
                minute=val.minute,
                second=getattr(val, "second", 0),
            )
        if isinstance(val, (int, float)):
            total_seconds = int(round(val * 86400))
            hours = (total_seconds // 3600) % 24
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            return pd.Timestamp(
                year=2000,
                month=1,
                day=1,
                hour=hours,
                minute=minutes,
                second=seconds,
            )

        val_str = str(val).strip()
        if not val_str or val_str.lower() in null_vals:
            return pd.NaT

        for fmt in formats:
            try:
                parsed = pd.to_datetime(val_str, format=fmt)
                if pd.notna(parsed):
                    return parsed
            except Exception:
                continue

        try:
            parsed = pd.to_datetime(val_str, format="mixed")
            if pd.notna(parsed):
                return parsed
        except Exception:
            pass
        return pd.NaT

    parsed_dt = series.apply(parse_single_val)
    return pd.to_datetime(parsed_dt, errors="coerce")


def _normalize_datetime_text(value) -> str:
    """Collapse whitespace: '01-04-2026  00:05:27' → '01-04-2026 00:05:27'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "nat", "null"}:
        return ""
    return re.sub(r"\s+", " ", text)


def _parse_one_datetime(text: str, config: dict):
    """
    Parse a single datetime string.

    Supports:
      - To-plaza VRN:  '11/26/2025 4:00:01 PM'  (US month/day + 12h AM/PM)
      - From-plaza exempt: '01-04-2026  00:05:27' (day-month + 24h)
    """
    text = _normalize_datetime_text(text)
    if not text:
        return pd.NaT

    upper = text.upper()
    has_ampm = " AM" in f" {upper}" or " PM" in f" {upper}" or upper.endswith("AM") or upper.endswith("PM")
    has_slash = "/" in text
    has_hyphen_date = bool(re.match(r"^\d{1,2}-\d{1,2}-\d{2,4}\b", text))

    # Prefer style-specific format lists first (avoids US/EU day-month swap).
    preferred: list[str] = []
    if has_ampm and has_slash:
        preferred.extend(config.get("datetime_formats_us_ampm") or [])
    if has_hyphen_date and not has_ampm:
        preferred.extend(config.get("datetime_formats_dayfirst") or [])
    preferred.extend(config.get("datetime_formats") or [])

    seen: set[str] = set()
    for fmt in preferred:
        if not fmt or fmt in seen:
            continue
        seen.add(fmt)
        try:
            parsed = pd.to_datetime(text, format=fmt)
            if pd.notna(parsed):
                return parsed
        except Exception:
            continue

    # Fallback: dayfirst for hyphen/day-month style; month-first for slash+AM/PM
    dayfirst = has_hyphen_date or (has_slash and not has_ampm)
    try:
        parsed = pd.to_datetime(text, dayfirst=dayfirst, errors="coerce")
        if pd.notna(parsed):
            return parsed
    except Exception:
        pass

    try:
        parsed = pd.to_datetime(text, dayfirst=not dayfirst, errors="coerce")
        if pd.notna(parsed):
            return parsed
    except Exception:
        pass

    return pd.NaT


def robust_parse_datetime(series, config: dict | None = None):
    config = config or load_config()

    if series is None or series.empty:
        return pd.Series(dtype="datetime64[ns]")

    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series)

    parsed = series.map(lambda v: _parse_one_datetime(v, config))
    return pd.to_datetime(parsed, errors="coerce")


def resolve_column_name(df, possible_sources):
    normalized_sources = [_norm_header_token(s) for s in possible_sources]
    for col in df.columns:
        if _norm_header_token(col) in normalized_sources:
            return col
    return None


def resolve_column(df, target_name, possible_sources):
    if target_name in df.columns:
        return df[target_name]
    col_name = resolve_column_name(df, possible_sources)
    if col_name is not None:
        return df[col_name]
    print(
        f"Warning: Column matching '{target_name}' not found. "
        f"Creating a blank column."
    )
    return pd.Series(np.nan, index=df.index)


# =========================================================
# MONTH-YEAR FILENAME MATCHING
# =========================================================


def extract_month_year(filename, config: dict | None = None):
    config = config or load_config()
    months = list(config.get("months") or [])
    default_year = str(config.get("default_year") or "2026")
    filename_upper = str(filename).upper()

    found_month = None
    for m in months:
        if m in filename_upper:
            found_month = m.title()
            break
    if not found_month:
        return None

    year_match = re.search(r"20\d{2}", filename_upper)
    if year_match:
        return (found_month, year_match.group(0))

    year_match_2d = re.search(r"[-_\s](\d{2})\b", filename_upper)
    if year_match_2d:
        return (found_month, "20" + year_match_2d.group(1))

    year_match_end = re.search(
        r"(\d{2})\.(xlsx|xls|csv)", filename_upper, re.IGNORECASE
    )
    if year_match_end:
        return (found_month, "20" + year_match_end.group(1))

    return (found_month, default_year)


# =========================================================
# SIDE LOGIC
# =========================================================


def map_side_from_plaza(lane_no, config: dict | None = None):
    config = config or load_config()
    lane_no = str(lane_no).strip().upper()
    side_a = {
        str(x).strip().upper()
        for x in (config.get("from_plaza_side_a_lanes") or [])
    }
    side_b = {
        str(x).strip().upper()
        for x in (config.get("from_plaza_side_b_lanes") or [])
    }
    if lane_no in side_a:
        return "Side A"
    if lane_no in side_b:
        return "Side B"
    return "Unknown"


def map_side_to_plaza(lane_no, config: dict | None = None):
    config = config or load_config()
    lane_no = str(lane_no).strip().upper()
    side_a = {
        str(x).strip().upper()
        for x in (config.get("to_plaza_side_a_lanes") or [])
    }
    side_b = {
        str(x).strip().upper()
        for x in (config.get("to_plaza_side_b_lanes") or [])
    }
    if lane_no in side_a:
        return "Side A"
    if lane_no in side_b:
        return "Side B"
    return "Unknown"


# =========================================================
# VRN DOWNLOAD (To plaza)
# =========================================================


def _load_vrn_module():
    path = VRN_DOWNLOAD_MERGE_PATH
    if not path.is_file():
        raise FileNotFoundError(f"VRN download script not found: {path}")
    spec = importlib.util.spec_from_file_location("e4_vrn_download_merge", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exempt_datetime_range(
    from_files: list[str],
    from_dir: str,
    config: dict,
) -> tuple[str, str]:
    """Min/max calendar dates from From-plaza exempt Date & Time columns."""
    from_aliases = config.get("from_plaza_column_aliases") or {}
    dt_aliases = list(from_aliases.get("Date & Time") or []) + [
        "Date & Time",
        "DATE & TIME",
    ]
    all_ts: list[pd.Timestamp] = []

    for name in from_files:
        path = os.path.join(from_dir, name)
        print(f"Scanning dates in From-plaza file: {name}")
        df = read_excel_smart(path, config)
        df.columns = [str(c).strip() for c in df.columns]

        # Apply same rename as merge so Date & Time resolves
        rename = {}
        alias_lookup: dict[str, str] = {}
        for canonical, names in from_aliases.items():
            for alias in names or []:
                alias_lookup[str(alias).strip().upper()] = canonical
        for col in df.columns:
            key = str(col).strip().upper()
            if key in alias_lookup:
                rename[col] = alias_lookup[key]
        df = df.rename(columns=rename)

        dt_col = None
        for alias in dt_aliases + ["Date & Time"]:
            hit = resolve_column_name(df, [alias])
            if hit:
                dt_col = hit
                break
        if not dt_col:
            print(f"  Warning: no Date & Time column in {name}; skipping.")
            continue

        parsed = robust_parse_datetime(df[dt_col], config)
        valid = parsed.dropna()
        if valid.empty:
            print(f"  Warning: no valid datetimes in {name}; skipping.")
            continue
        all_ts.extend(valid.tolist())
        print(
            f"  {name}: {valid.min()} → {valid.max()} "
            f"({len(valid)} valid timestamps)"
        )

    if not all_ts:
        raise RuntimeError(
            "Could not determine date range from From-plaza exempt files. "
            "Check Date & Time columns."
        )

    series = pd.to_datetime(pd.Series(all_ts))
    start = series.min().date().isoformat()
    end = series.max().date().isoformat()
    print(f"Exempt date range for VRN download: {start} → {end}")
    return start, end


def run_to_plaza_vrn_download_merge(
    entity_name: str,
    from_date: str,
    to_date: str,
    config: dict,
) -> Path:
    """Download + merge VRN using E15_config vrn_merge (required columns only)."""
    vrn_cfg = config.get("vrn_merge") or {}
    if not vrn_cfg.get("merge_columns"):
        raise RuntimeError("E15_config.json vrn_merge.merge_columns is empty.")

    load_env()
    vrn_mod = _load_vrn_module()
    vrn_mod.load_env = load_env
    start, end = vrn_mod.validate_interval(from_date, to_date)

    download_folder = Path(VRN_DOWNLOAD_FOLDER)
    download_folder.mkdir(parents=True, exist_ok=True)
    out_dir = Path(FALLBACK_OUTPUT_FOLDER)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"VRN source DB: {require_env('DB_NAME')} "
        f"table={os.getenv('Table_NAME', 'submissions')}"
    )
    print(f"To-plaza entity_name: {entity_name}")
    print("Connecting to DB for VRN download…")
    with psycopg2.connect(**vrn_mod.connection_kwargs()) as conn:
        local_paths, _stats = vrn_mod.download_vrn_files(
            conn,
            entity_name=entity_name,
            start=start,
            end=end,
            output_folder=download_folder,
            skip_existing=True,
        )

    paths = local_paths or vrn_mod.list_local_files(
        download_folder / vrn_mod.safe_part(entity_name)
    )
    if not paths:
        paths = vrn_mod.list_local_files(download_folder)
    if not paths:
        raise FileNotFoundError(
            f"No VRN files downloaded for entity={entity_name!r} "
            f"range {start.isoformat()} → {end.isoformat()}"
        )

    merged_name = (
        f"{vrn_mod.safe_part(entity_name)}_"
        f"{start.isoformat()}_{end.isoformat()}_merged_vrn.csv"
    )
    merged_path = vrn_mod.merge_vrn_files(
        paths,
        vrn_cfg,
        out_dir / merged_name,
    )
    vrn_mod.delete_downloaded_files(paths, download_folder)
    print(f"VRN merge columns: {list((vrn_cfg.get('merge_columns') or {}).keys())}")
    print(f"Merged To-plaza VRN: {merged_path}")
    return Path(merged_path)


# =========================================================
# CORE MERGING ENGINE
# =========================================================


def process_and_merge(from_path, to_path, config: dict | None = None):
    config = config or load_config()
    to_aliases = config.get("to_plaza_column_aliases") or {}
    from_aliases = config.get("from_plaza_column_aliases") or {}
    match_max_hours = float(config.get("match_max_hours") or 2)
    min_vrn_len = int(config.get("min_vrn_length") or 6)
    custom_keep = str(
        config.get("from_plaza_custom_keep_value") or "exception"
    ).strip().lower()

    print("\n--------------------------------------------------")
    print("Processing matched pair:")
    print(f" From-plaza file: {from_path}")
    print(f" To-plaza VRN:    {to_path}")
    print("--------------------------------------------------")

    from_df = read_excel_smart(from_path, config)
    to_df = read_table_smart(to_path, config)

    from_df.columns = [str(c).strip() for c in from_df.columns]
    to_df.columns = [str(c).strip().upper() for c in to_df.columns]

    # Normalize From-plaza column names via config aliases
    from_rename = {}
    alias_lookup: dict[str, str] = {}
    for canonical, names in from_aliases.items():
        for name in names or []:
            alias_lookup[str(name).strip().upper()] = canonical
    for col in from_df.columns:
        col_clean = str(col).strip().upper()
        if col_clean in alias_lookup:
            from_rename[col] = alias_lookup[col_clean]
    from_df = from_df.rename(columns=from_rename)

    # Filter From-plaza — keep exception rows only
    if "Custom" in from_df.columns:
        from_df["Custom"] = from_df["Custom"].astype(str).str.strip().str.lower()
        from_df = from_df[from_df["Custom"] == custom_keep].copy()
    else:
        print(
            "Warning: 'Custom' column not found in From-plaza file. "
            "Skipping exception filtering."
        )

    # Clean From-plaza VRN
    if "Veh Reg No." in from_df.columns:
        from_df["Veh Reg No."] = (
            from_df["Veh Reg No."]
            .astype(str)
            .str.upper()
            .str.replace(" ", "", regex=False)
            .str.strip()
        )
        from_df = from_df[from_df["Veh Reg No."].str.len() > min_vrn_len].copy()
    else:
        print("Error: 'Veh Reg No.' column not found in From-plaza file.")
        return None

    # Map sides
    if "Lane No" in from_df.columns:
        from_df["SIDE"] = from_df["Lane No"].apply(
            lambda x: map_side_from_plaza(x, config)
        )
    else:
        from_df["SIDE"] = "Unknown"

    to_lane_col = resolve_column_name(to_df, to_aliases.get("lane") or [])
    if to_lane_col:
        to_df["SIDE"] = to_df[to_lane_col].apply(
            lambda x: map_side_to_plaza(x, config)
        )
    else:
        to_df["SIDE"] = "Unknown"

    # Datetimes
    date_time_col = (
        "Date & Time"
        if "Date & Time" in from_df.columns
        else (
            "DATE & TIME"
            if "DATE & TIME" in from_df.columns
            else from_df.columns[0]
        )
    )
    from_df["DATE_TIME_FROM"] = robust_parse_datetime(
        from_df[date_time_col], config
    )

    to_date_col = resolve_column_name(to_df, to_aliases.get("datetime") or [])
    if to_date_col:
        to_df["DATE_TIME_TO"] = robust_parse_datetime(to_df[to_date_col], config)
    else:
        to_df["DATE_TIME_TO"] = pd.NaT

    from_df = from_df[from_df["DATE_TIME_FROM"].notna()].copy()
    to_df = to_df[to_df["DATE_TIME_TO"].notna()].copy()

    # Clean To-plaza VRN
    vrn_col_to = resolve_column_name(to_df, to_aliases.get("vehicle") or [])
    if vrn_col_to:
        to_df["CLEAN_VRN"] = (
            to_df[vrn_col_to]
            .astype(str)
            .str.upper()
            .str.replace(" ", "", regex=False)
            .str.strip()
        )
    else:
        to_df["CLEAN_VRN"] = ""

    to_subset = pd.DataFrame(index=to_df.index)
    to_subset["Veh Reg No."] = to_df["CLEAN_VRN"]
    to_subset["SIDE"] = to_df["SIDE"]
    to_subset["DATE_TIME_TO"] = to_df["DATE_TIME_TO"]
    to_subset["PAYMENT METHOD"] = resolve_column(
        to_df, "PAYMENT METHOD", to_aliases.get("PAYMENT METHOD") or []
    )
    to_subset["SVC FARE"] = resolve_column(
        to_df, "SVC FARE", to_aliases.get("SVC FARE") or []
    )
    to_subset["DESCRIPTION"] = resolve_column(
        to_df, "DESCRIPTION", to_aliases.get("DESCRIPTION") or []
    )
    to_subset["CCH TRANSACTION ID"] = resolve_column(
        to_df, "CCH TRANSACTION ID", to_aliases.get("CCH TRANSACTION ID") or []
    )
    to_subset["TC Class"] = resolve_column(
        to_df,
        "TC Class",
        (config.get("tc_class_column_aliases") or [])
        + list((config.get("to_plaza_column_aliases") or {}).get("TC Class") or []),
    )
    to_subset["Journey Type"] = resolve_column(
        to_df,
        "Journey Type",
        (config.get("journey_type_column_aliases") or [])
        + list(
            (config.get("to_plaza_column_aliases") or {}).get("Journey Type") or []
        ),
    )

    merged = from_df.merge(
        to_subset,
        on=["Veh Reg No.", "SIDE"],
        how="left",
        suffixes=("", "_TO"),
    )

    merged["TIME_DIFF_HOURS"] = (
        (merged["DATE_TIME_FROM"] - merged["DATE_TIME_TO"]).abs()
        / pd.Timedelta(hours=1)
    )
    merged["MATCH"] = merged["TIME_DIFF_HOURS"].apply(
        lambda x: "Yes" if (pd.notna(x) and x <= match_max_hours) else "No"
    )

    if "MATCH" in merged.columns:
        match_clean = merged["MATCH"].astype(str).str.strip().str.upper()
        before_match_count = len(merged)
        merged = merged[match_clean == "YES"].copy()
        print(
            f"MATCH filter applied: "
            f"{before_match_count - len(merged)} rows with MATCH != YES removed."
        )
    else:
        print("Warning: MATCH column not found.")

    if "PAYMENT METHOD" in merged.columns:
        payment_method_clean = (
            merged["PAYMENT METHOD"].astype(str).str.strip().str.upper()
        )
        before_exempt_count = len(merged)
        merged = merged[payment_method_clean != "EXEMPT"].copy()
        print(
            f"EXEMPT filter applied: "
            f"{before_exempt_count - len(merged)} EXEMPT rows removed."
        )
    else:
        print(
            "Warning: PAYMENT METHOD column not found. EXEMPT filter skipped."
        )

    if not merged.empty:
        merged = merged.sort_values(by="TIME_DIFF_HOURS", ascending=True)
        merged = merged.drop_duplicates(
            subset=["Veh Reg No.", "DATE_TIME_FROM"], keep="first"
        )

    print(f"SUCCESS: Merged pair successfully. Total Rows: {len(merged)}")
    return merged


# =========================================================
# APPLICABLE RATE (TC Class + Journey Type → plaza_rates)
# =========================================================


def _normalize_value_key(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[\s_\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in {"", "nan", "none", "nat"}:
        return ""
    return text


def _vehicle_class_label_indexes() -> dict[str, int]:
    """Indexes from E10 vehicle-class.py WEIGHT_RANGE_INDEXES + OSV=6."""
    lookup: dict[str, int] = {}
    for _bound, idx, label in WEIGHT_RANGE_INDEXES:
        key = _normalize_value_key(label)
        if key:
            lookup[key] = int(idx)
    lookup[_normalize_value_key("OSV")] = 6
    return lookup


def build_tc_class_index_lookup(config: dict) -> dict[str, int]:
    """
    Index map:
      - base labels from vehicle-class.py (Car→1 … MAV→5, OSV→6)
      - plus aliases in E15_config tc_class_index_map (index → name list)
    """
    lookup = _vehicle_class_label_indexes()
    raw = config.get("tc_class_index_map") or {}
    for idx_raw, names in raw.items():
        idx = int(idx_raw)
        for name in names or []:
            key = _normalize_value_key(name)
            if key:
                lookup[key] = idx
    if not lookup:
        raise RuntimeError("tc_class_index_map / vehicle-class labels produced empty lookup")
    return lookup


def build_tc_class_skip_set(config: dict) -> set[str]:
    return {
        _normalize_value_key(v)
        for v in (config.get("tc_class_skip_list") or [])
        if _normalize_value_key(v)
    }


def build_journey_type_lookup(config: dict) -> dict[str, str]:
    """Alias → plaza_rates key (single / return / local)."""
    lookup: dict[str, str] = {}
    for category, names in (config.get("journey_type_map") or {}).items():
        cat = str(category).strip().lower()
        if not cat:
            continue
        lookup[_normalize_value_key(cat)] = cat
        for name in names or []:
            key = _normalize_value_key(name)
            if key:
                lookup[key] = cat
    if not lookup:
        raise RuntimeError("journey_type_map is empty in E15_config.json")
    return lookup


def parse_rate_cutover_date(config: dict) -> date:
    """First day when Plaza_Rates_Apr26_onwards applies (default: after April 2026)."""
    raw = str(config.get("rate_cutover_date") or "2026-05-01").strip()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid rate_cutover_date: {raw!r}") from exc


def select_plaza_rates_book(read_d: date, cutover: date) -> dict:
    """
    On/before day before cutover → PLAZA_RATES.
    On/after cutover (default 2026-05-01 = after April 2026) → Plaza_Rates_Apr26_onwards.
    """
    if read_d < cutover:
        return PLAZA_RATES
    return Plaza_Rates_Apr26_onwards


def resolve_rate_date_series(df: pd.DataFrame, config: dict) -> tuple[pd.Series, str]:
    """Pick best datetime column for rate cutover (To-plaza first, then From)."""
    candidates: list[str] = [
        "DATE_TIME_TO",
        "DATE_TIME_FROM",
        "Date & Time",
        "Date & Time_TO",
    ]
    for alias in config.get("to_plaza_column_aliases", {}).get("datetime") or []:
        text = str(alias).strip()
        if text and text not in candidates:
            candidates.append(text)
    for alias in (config.get("from_plaza_column_aliases") or {}).get("Date & Time") or []:
        text = str(alias).strip()
        if text and text not in candidates:
            candidates.append(text)

    for candidate in candidates:
        if candidate not in df.columns:
            continue
        parsed = pd.to_datetime(df[candidate], errors="coerce", format="mixed")
        if parsed.notna().any():
            return parsed, candidate

    # Last resort: Source Month like "APR 2026" / "Apr 2026"
    if "Source Month" in df.columns:
        months = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }

        def _parse_source_month(value):
            text = str(value or "").strip()
            if not text or text.lower() in {"nan", "none"}:
                return pd.NaT
            parts = text.replace("-", " ").replace("/", " ").split()
            if len(parts) < 2:
                return pd.NaT
            mon = months.get(parts[0][:3].lower())
            try:
                year = int(parts[1])
            except ValueError:
                return pd.NaT
            if not mon:
                return pd.NaT
            # Use mid-month day for cutover comparison
            return pd.Timestamp(year=year, month=mon, day=15)

        parsed = df["Source Month"].map(_parse_source_month)
        if parsed.notna().any():
            return pd.to_datetime(parsed), "Source Month"

    return pd.Series([pd.NaT] * len(df), index=df.index), ""


def lookup_journey_rate(
    entity_name: str,
    rates_book: dict,
    journey_key: str,
    class_index: int,
) -> float:
    key = str(entity_name or "").strip()
    plaza = rates_book.get(key) or rates_book.get(key.lower())
    if plaza is None:
        book = (
            "PLAZA_RATES"
            if rates_book is PLAZA_RATES
            else "Plaza_Rates_Apr26_onwards"
        )
        raise RuntimeError(f"Entity {entity_name!r} not found in plaza rates ({book})")
    journey_rates = plaza.get(journey_key) if isinstance(plaza, dict) else None
    if not isinstance(journey_rates, dict):
        raise RuntimeError(f"No {journey_key!r} rates for entity {entity_name!r}")
    if class_index not in journey_rates:
        raise RuntimeError(
            f"No {journey_key!r} rate for class index {class_index} "
            f"on entity {entity_name!r}"
        )
    return float(journey_rates[class_index])


def apply_applicable_rates(
    df: pd.DataFrame,
    config: dict,
    entity_name: str,
) -> pd.DataFrame:
    """
    Add Applicable Rate from TC Class index + Journey Type using plaza_rates.
    Date after April 2026 (on/after rate_cutover_date) → Plaza_Rates_Apr26_onwards.
    Unknown non-skipped TC Class / Journey Type stops the run.
    """
    if df is None or df.empty:
        return df

    tc_aliases = list(config.get("tc_class_column_aliases") or [])
    journey_aliases = list(config.get("journey_type_column_aliases") or [])
    tc_col = resolve_column_name(df, tc_aliases)
    journey_col = resolve_column_name(df, journey_aliases)

    missing = []
    if not tc_col:
        missing.append("TC Class")
    if not journey_col:
        missing.append("Journey Type")
    if missing:
        raise RuntimeError(
            "Cannot compute Applicable Rate — missing columns: "
            + ", ".join(missing)
            + f". Available: {list(df.columns)}"
        )

    out_col = str(config.get("applicable_rate_output") or "Applicable Rate").strip()
    if not out_col:
        out_col = "Applicable Rate"

    cutover = parse_rate_cutover_date(config)
    tc_lookup = build_tc_class_index_lookup(config)
    skip_set = build_tc_class_skip_set(config)
    journey_lookup = build_journey_type_lookup(config)

    date_series, date_col_used = resolve_rate_date_series(df, config)
    if not date_col_used:
        raise RuntimeError(
            "Cannot apply date-based rates — no datetime column found "
            f"(need DATE_TIME_TO / DATE_TIME_FROM / Date & Time). "
            f"Available: {list(df.columns)}"
        )
    print(
        f"Rate date column: {date_col_used!r} "
        f"(before {cutover.isoformat()} → PLAZA_RATES; "
        f"on/after → Plaza_Rates_Apr26_onwards)"
    )

    rates: list[float | None] = []
    rated = 0
    skipped = 0
    used_old = 0
    used_apr26 = 0
    missing_date = 0
    unknown_tc: set[str] = set()
    unknown_journey: set[str] = set()

    for tc_raw, journey_raw, ts in zip(
        df[tc_col].tolist(),
        df[journey_col].tolist(),
        date_series.tolist(),
    ):
        tc_key = _normalize_value_key(tc_raw)
        journey_key = _normalize_value_key(journey_raw)

        if tc_key and tc_key in skip_set:
            rates.append(None)
            skipped += 1
            continue

        if ts is None or pd.isna(ts):
            rates.append(None)
            missing_date += 1
            continue

        if not tc_key or not journey_key:
            rates.append(None)
            continue

        if tc_key not in tc_lookup:
            unknown_tc.add(str(tc_raw).strip())
            rates.append(None)
            continue

        journey_cat = journey_lookup.get(journey_key)
        if journey_cat is None:
            unknown_journey.add(str(journey_raw).strip())
            rates.append(None)
            continue

        class_index = tc_lookup[tc_key]
        read_d = pd.Timestamp(ts).date()
        rates_book = select_plaza_rates_book(read_d, cutover)
        if rates_book is Plaza_Rates_Apr26_onwards:
            used_apr26 += 1
        else:
            used_old += 1
        rate = lookup_journey_rate(entity_name, rates_book, journey_cat, class_index)
        rates.append(rate)
        rated += 1

    if unknown_tc:
        raise RuntimeError(
            "Unknown TC Class value(s) not in vehicle-class / tc_class_index_map — "
            "stopping: " + ", ".join(sorted(repr(v) for v in unknown_tc))
        )
    if unknown_journey:
        raise RuntimeError(
            "Unknown Journey Type value(s) not in journey_type_map — stopping: "
            + ", ".join(sorted(repr(v) for v in unknown_journey))
        )

    result = df.copy()
    result[out_col] = rates
    total_amount = float(pd.to_numeric(result[out_col], errors="coerce").fillna(0).sum())
    print(
        f"Applicable Rate for entity {entity_name!r}: "
        f"{rated}/{len(result)} rated "
        f"(PLAZA_RATES={used_old}, Apr26_onwards={used_apr26}"
        + (f", missing date={missing_date}" if missing_date else "")
        + (f", skipped TC={skipped}" if skipped else "")
        + f"), Total Amount={total_amount:,.2f}"
    )
    return result


# =========================================================
# MAIN BATCH PROCESSING ROUTINE
# =========================================================


def main():
    print("=" * 60)
    print("E15 — From-plaza exempt + To-plaza VRN download/merge")
    print("=" * 60)

    config = load_config()
    entity_name = resolve_entity_name()
    print(f"TO_PLAZA_ENTITY_NAME: {entity_name}")
    plaza_identifier = ""
    if UPDATE_DB:
        plaza_identifier = resolve_plaza_identifier()
        print(f"PLAZA_IDENTIFIER: {plaza_identifier}")
        print(f"EXCEPTION_TYPE_ID: {EXCEPTION_TYPE_ID}")
        print(f"UPDATE_DB: {UPDATE_DB} (dry_run={DB_DRY_RUN})")
    else:
        print("UPDATE_DB: False")

    from_folder = str(FROM_PLAZA_FOLDER or "").strip()
    output_folder = str(OUTPUT_FOLDER or "").strip()
    fallback_from = str(FALLBACK_FROM_PLAZA_FOLDER)
    fallback_out = str(FALLBACK_OUTPUT_FOLDER)
    individual_prefix = str(INDIVIDUAL_OUTPUT_PREFIX or "from_to")
    combined_filename = str(COMBINED_OUTPUT_FILENAME or "from_to_combined.xlsx")

    if os.path.exists(from_folder):
        from_dir = from_folder
        output_dir = output_folder or fallback_out
    else:
        print("\nWarning: Could not access configured From-plaza folder.")
        print("\nCreating local folder for execution:")
        from_dir = fallback_from
        output_dir = fallback_out
        os.makedirs(from_dir, exist_ok=True)
        print(f" - Place From-plaza Excel files in: '{from_dir}'")

    os.makedirs(output_dir, exist_ok=True)

    from_files = [
        f
        for f in os.listdir(from_dir)
        if f.endswith((".xlsx", ".xls", ".csv")) and not f.startswith("~$")
    ]
    if not from_files:
        print(f"No From-plaza files found in: {from_dir}")
        return

    print("\nScanning From-plaza folder:")
    print(f" -> '{from_dir}': found {len(from_files)} files: {from_files}")

    print("-" * 60)
    from_date, to_date = exempt_datetime_range(from_files, from_dir, config)

    print("-" * 60)
    print("Downloading / merging To-plaza VRN…")
    vrn_path = run_to_plaza_vrn_download_merge(
        entity_name, from_date, to_date, config
    )

    all_merged_dfs = []
    success_count = 0

    for name in from_files:
        from_path = os.path.join(from_dir, name)
        my = extract_month_year(name, config)
        try:
            merged_df = process_and_merge(from_path, vrn_path, config)
            if merged_df is not None and not merged_df.empty:
                merged_df = apply_applicable_rates(
                    merged_df, config, entity_name
                )
                if my and isinstance(my, tuple):
                    month_label = f"{my[0]} {my[1]}"
                    ind_filename = f"{individual_prefix}_{my[0]}_{my[1]}.xlsx"
                else:
                    month_label = Path(name).stem
                    ind_filename = f"{individual_prefix}_{Path(name).stem}.xlsx"

                merged_df.insert(0, "Source Month", month_label)
                ind_out_path = os.path.join(output_dir, ind_filename)
                merged_df.to_excel(ind_out_path, index=False)
                print(f"Saved individual sheet to: {ind_out_path}")
                all_merged_dfs.append(merged_df)
                success_count += 1
            else:
                print(
                    "No data remaining after MATCH = YES and "
                    "PAYMENT METHOD != EXEMPT filtering."
                )
        except Exception as e:
            print(f"ERROR processing {name}: {e}")

    if all_merged_dfs:
        print("\nCombining all processed files into one single Excel file...")
        final_combined_df = pd.concat(all_merged_dfs, ignore_index=True)

        if "MATCH" in final_combined_df.columns:
            final_combined_df = final_combined_df[
                final_combined_df["MATCH"].astype(str).str.strip().str.upper()
                == "YES"
            ].copy()

        if "PAYMENT METHOD" in final_combined_df.columns:
            final_combined_df = final_combined_df[
                final_combined_df["PAYMENT METHOD"]
                .astype(str)
                .str.strip()
                .str.upper()
                != "EXEMPT"
            ].copy()

        # Ensure Applicable Rate present (re-apply if filtered changed set)
        rate_col = str(config.get("applicable_rate_output") or "Applicable Rate")
        if rate_col not in final_combined_df.columns:
            final_combined_df = apply_applicable_rates(
                final_combined_df, config, entity_name
            )

        out_path = os.path.join(output_dir, combined_filename)
        try:
            final_combined_df.to_excel(out_path, index=False)
            print("\n====================================")
            print("COMBINED FILE EXPORTED SUCCESSFULLY")
            print("====================================")
            print(f"Path: {out_path}")
            print(f"Final Output Rows: {len(final_combined_df)}")
            if rate_col in final_combined_df.columns:
                total_amt = float(
                    pd.to_numeric(final_combined_df[rate_col], errors="coerce")
                    .fillna(0)
                    .sum()
                )
                print(f"Total Applicable Rate: {total_amt:,.2f}")
        except Exception as e:
            print(f"\nCould not write directly to {out_path}")
            print(f"Reason: {e}")
            fallback_path = combined_filename
            print(f"Exporting to current folder: {fallback_path}")
            final_combined_df.to_excel(fallback_path, index=False)
            print("COMBINED FILE EXPORTED SUCCESSFULLY TO FALLBACK PATH")

        if UPDATE_DB:
            print("-" * 60)
            print(
                f"Updating audit_exception_metrics "
                f"(exception_type_id={EXCEPTION_TYPE_ID})…"
            )
            date_col_cfg = str(
                (config.get("columns") or {}).get("date_time") or "Date & Time"
            )
            update_db_from_dataframe(
                final_combined_df,
                plaza_identifier,
                exception_type_id=int(EXCEPTION_TYPE_ID),
                dry_run=bool(DB_DRY_RUN),
                date_aliases=[
                    date_col_cfg,
                    "Date & Time",
                    "DATE_TIME_FROM",
                    "DATE_TIME_TO",
                ],
                rate_aliases=[rate_col, "Applicable Rate"],
            )
        else:
            print("UPDATE_DB=False — audit_exception_metrics not updated.")
    else:
        print(
            "\nNo data was successfully merged. Combined file was not created."
        )
        if UPDATE_DB:
            print("UPDATE_DB skipped — no combined data.")

    print("\n====================================")
    print(
        f"BATCH RUN COMPLETED: {success_count}/{len(from_files)} "
        f"FROM-PLAZA FILE(S) PROCESSED SUCCESSFULLY"
    )
    print(f"Merged output saved in: {output_dir}")
    print(f"To-plaza VRN used: {vrn_path}")
    print("FINAL CONDITION:")
    print("MATCH = YES")
    print("PAYMENT METHOD != EXEMPT")
    print("====================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
