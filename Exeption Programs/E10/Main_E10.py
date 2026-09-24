"""
E10 — Local VRN folder + checkpost Weight + ETC download/merge + overweight.

1) Load/merge VRN from VRN_INPUT_FOLDER (DATE+TIME combined when split)
2) Derive FROM_DATE / TO_DATE from VRN datetime for ETC download
3) Drop excluded TC Class; attach checkpost Weight; drop invalid weight
4) Download/merge ETC; join on vehicle + date/hour (or date if date-only)
5) Custom band, Weight Group, Std Weight, Applicable Rate (plaza single)
6) Overweight / Overweight %; keep Overweight>0 and overload/SWB amt = 0
7) OW Status (OW At WIM / Not Charged At SWB / Altered at WIM/SWB)

Run:
  1. Set ENTITY_NAME and VRN_INPUT_FOLDER
  2. python Main_E10.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

BASE_DIR = Path(__file__).resolve().parent
E4_DIR = BASE_DIR.parent / "E4"
WEBSITE_ENV = BASE_DIR.parent.parent / "Website" / "backend" / ".env"
E4_ENV = E4_DIR / ".env"
CONFIG_PATH = BASE_DIR / "e10_config.json"
VRN_DOWNLOAD_MERGE_PATH = E4_DIR / "vrn-download-merge.py"
ETC_DOWNLOAD_MERGE_PATH = E4_DIR / "etc-download-merge.py"
VEHICLE_CLASS_PATH = BASE_DIR / "vehicle-class.py"
PLAZA_RATES_PATH = E4_DIR / "plaza_rates.py"
OUTPUT_DIR = BASE_DIR / "output"
ETC_DOWNLOAD_FOLDER = BASE_DIR / "etc_downloads"


def _load_module_from_path(path: Path, module_name: str):
    if not path.is_file():
        raise FileNotFoundError(f"Module file not found: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PLAZA_RATES_MOD = _load_module_from_path(PLAZA_RATES_PATH, "e4_plaza_rates")
PLAZA_RATES = _PLAZA_RATES_MOD.PLAZA_RATES
Plaza_Rates_Apr26_onwards = _PLAZA_RATES_MOD.Plaza_Rates_Apr26_onwards


def _load_vehicle_class_module():
    return _load_module_from_path(VEHICLE_CLASS_PATH, "e10_vehicle_class")


_VEHICLE_CLASS_MOD = _load_vehicle_class_module()
WEIGHT_RANGE_INDEXES = _VEHICLE_CLASS_MOD.WEIGHT_RANGE_INDEXES

# --- Runtime inputs (edit these; not in config) ---
ENTITY_NAME = "bassi"
# Local VRN folder (Excel/CSV). Required — VRN is not downloaded.
VRN_INPUT_FOLDER = r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E10\Combined VRNs"
VRN_OUTPUT_FILE = OUTPUT_DIR / "e10_vrn_with_weight.csv"
ETC_OUTPUT_FILE = OUTPUT_DIR / "e10_merged_etc.csv"
MERGED_VRN_ETC_OUTPUT_FILE = OUTPUT_DIR / "e10_vrn_etc_merged.csv"


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_env() -> None:
    """Load Website + E4 .env files and map names used by downloads / checkpost."""
    if not WEBSITE_ENV.is_file():
        raise FileNotFoundError(f"Env file not found: {WEBSITE_ENV}")
    load_dotenv(WEBSITE_ENV, override=True)

    # ETC / submissions (E4 etc-download-merge expects DB_NAME + Table_NAME)
    source_db = os.getenv("Source_DB_NAME", "").strip()
    if source_db:
        os.environ["DB_NAME"] = source_db
    table = (
        os.getenv("exceptions_Table_NAME", "").strip()
        or os.getenv("Table_NAME", "").strip()
        or "submissions"
    )
    os.environ["Table_NAME"] = table

    # Checkpost lives in E4/.env (Checkpost_DB_NAME / Checkpost_Table_NAME).
    # override=False so Website Source_DB_NAME → DB_NAME mapping stays intact.
    if E4_ENV.is_file():
        load_dotenv(E4_ENV, override=False)

    # Accept CHECKPOST_* aliases if Checkpost_* not already set
    if not os.getenv("Checkpost_DB_NAME", "").strip():
        alias_db = os.getenv("CHECKPOST_DB", "").strip()
        if alias_db:
            os.environ["Checkpost_DB_NAME"] = alias_db
    if not os.getenv("Checkpost_Table_NAME", "").strip():
        alias_table = os.getenv("CHECKPOST_TABLE", "").strip()
        if alias_table:
            os.environ["Checkpost_Table_NAME"] = alias_table


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        searched = f"{WEBSITE_ENV}"
        if E4_ENV.is_file():
            searched += f" and {E4_ENV}"
        raise RuntimeError(f"Missing required env var: {name} (checked {searched})")
    return value


def checkpost_connection_kwargs() -> dict:
    load_env()
    return {
        "host": require_env("DB_HOST"),
        "port": int(os.getenv("DB_PORT") or "5432"),
        "user": require_env("DB_USER"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": require_env("Checkpost_DB_NAME"),
    }


def checkpost_table_name() -> str:
    return (
        os.getenv("Checkpost_Table_NAME", "").strip()
        or os.getenv("CHECKPOST_TABLE", "").strip()
        or "checkpostmaster"
    )


def _normalize_header_cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return " ".join(text.split())


def _normalize_header_key(value) -> str:
    return _normalize_header_cell(value).casefold()


def normalize_vehicle_number(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().upper()
    if text in {"", "NAN", "NONE", "NAT"}:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text)


def normalize_tc_class_key(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    if text in {"", "nan", "none", "nat"}:
        return ""
    return text


def resolve_column(headers: list[str], aliases: list[str]) -> str | None:
    by_key = {_normalize_header_key(h): h for h in headers if _normalize_header_cell(h)}
    for alias in aliases or []:
        key = _normalize_header_key(alias)
        if key in by_key:
            return by_key[key]
    return None


def resolve_entity_name() -> str:
    entity = ENTITY_NAME
    if len(sys.argv) >= 2 and str(sys.argv[1]).strip():
        entity = str(sys.argv[1]).strip()
    entity = str(entity or "").strip()
    if not entity:
        entity = input("Enter entity_name: ").strip()
    if not entity:
        raise RuntimeError("entity_name is required.")
    return entity


def resolve_vrn_input_folder() -> Path:
    folder = Path(str(VRN_INPUT_FOLDER or "").strip())
    if len(sys.argv) >= 3 and str(sys.argv[2]).strip():
        folder = Path(str(sys.argv[2]).strip())
    if not folder.is_dir():
        raise FileNotFoundError(
            f"VRN_INPUT_FOLDER not found or not a directory: {folder}"
        )
    return folder


def _load_module(path: Path, module_name: str):
    if not path.is_file():
        raise FileNotFoundError(f"Script not found: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_vrn_download_merge_module():
    return _load_module(VRN_DOWNLOAD_MERGE_PATH, "e4_vrn_download_merge")


def load_etc_download_merge_module():
    return _load_module(ETC_DOWNLOAD_MERGE_PATH, "e4_etc_download_merge")


def drop_excluded_tc_class_rows(vrn_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    headers = [str(c) for c in vrn_df.columns]
    tc_col = resolve_column(headers, config.get("tc_class_column_aliases") or [])
    if not tc_col:
        raise RuntimeError(
            "TC Class column not found on merged VRN. "
            f"Available: {list(vrn_df.columns)}"
        )

    exclude = {
        normalize_tc_class_key(v)
        for v in (config.get("tc_class_exclude") or [])
        if normalize_tc_class_key(v)
    }
    if not exclude:
        print("tc_class_exclude is empty — no TC Class rows dropped.")
        return vrn_df

    keys = vrn_df[tc_col].map(normalize_tc_class_key)
    keep = ~keys.isin(exclude)
    dropped = int((~keep).sum())
    out = vrn_df.loc[keep].reset_index(drop=True)
    print(
        f"Dropped {dropped} rows with TC Class in {sorted(exclude)} "
        f"({len(out)} remaining)"
    )
    return out


def fetch_checkpost_weight_lookup(
    vehicle_numbers: list[str],
    config: dict,
) -> dict[str, str]:
    """Map normalized Unique Vehicle Number → weight (as stored text)."""
    unique_vehs = sorted({v for v in vehicle_numbers if v})
    if not unique_vehs:
        return {}

    load_env()
    table = checkpost_table_name()
    veh_col = str(
        config.get("checkpost_vehicle_column") or "Unique Vehicle Number"
    ).strip()
    weight_col = str(config.get("checkpost_weight_column") or "weight").strip()
    batch_size = int(config.get("checkpost_fetch_batch_size") or 1000)

    query = sql.SQL(
        """
        SELECT {veh} AS vehicle_no, {weight} AS weight
        FROM {table}
        WHERE regexp_replace(upper(COALESCE({veh}, '')), '[^A-Z0-9]', '', 'g') = ANY(%s)
        """
    ).format(
        table=sql.Identifier(table),
        veh=sql.Identifier(veh_col),
        weight=sql.Identifier(weight_col),
    )

    lookup: dict[str, str] = {}
    print(
        f"Fetching checkpost weights from {require_env('Checkpost_DB_NAME')}.{table} "
        f"for {len(unique_vehs):,} unique vehicles…"
    )
    with psycopg2.connect(**checkpost_connection_kwargs()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            for start in range(0, len(unique_vehs), batch_size):
                batch = unique_vehs[start : start + batch_size]
                cursor.execute(query, (batch,))
                rows = cursor.fetchall()
                for row in rows:
                    veh = normalize_vehicle_number(row.get("vehicle_no"))
                    if not veh or veh in lookup:
                        continue
                    weight_raw = row.get("weight")
                    if weight_raw is None or (
                        isinstance(weight_raw, float) and pd.isna(weight_raw)
                    ):
                        continue
                    weight_text = str(weight_raw).strip()
                    if weight_text == "" or weight_text.lower() in {"nan", "none"}:
                        continue
                    lookup[veh] = weight_text

    print(f"  Checkpost weight hits: {len(lookup):,}/{len(unique_vehs):,}")
    return lookup


def attach_weight_from_checkpost(
    vrn_df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    headers = [str(c) for c in vrn_df.columns]
    veh_col = resolve_column(headers, config.get("vehicle_column_aliases") or [])
    if not veh_col:
        raise RuntimeError(
            "Vehicle column not found on merged VRN. "
            f"Available: {list(vrn_df.columns)}"
        )

    out_col = str(config.get("weight_output_column") or "Weight").strip() or "Weight"
    vehs = vrn_df[veh_col].map(normalize_vehicle_number)
    lookup = fetch_checkpost_weight_lookup(vehs.tolist(), config)

    weights = [lookup.get(v, "") for v in vehs.tolist()]
    result = vrn_df.copy()
    result[out_col] = weights
    matched = sum(1 for w in weights if w != "")
    print(
        f"Weight attached via checkpost on {veh_col!r} → {out_col!r}: "
        f"{matched}/{len(result)} rows matched"
    )
    return result


def drop_invalid_weight_rows(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    headers = [str(c) for c in df.columns]
    weight_col = resolve_column(
        headers,
        [
            str(config.get("weight_output_column") or "Weight"),
            "Weight",
            "weight",
        ],
    )
    if not weight_col:
        raise RuntimeError(
            "Weight column not found after checkpost lookup. "
            f"Available: {list(df.columns)}"
        )

    invalid = {
        str(v).strip().casefold()
        for v in (config.get("weight_invalid_values") or [])
    }
    invalid.update({"", "0", "0.0", "n/a", "na", "null", "none", "nan", "nat"})

    def is_valid(value) -> bool:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return False
        text = str(value).strip()
        if text.casefold() in invalid:
            return False
        try:
            if float(text.replace(",", "")) == 0.0:
                return False
        except ValueError:
            pass
        return True

    keep = df[weight_col].map(is_valid)
    dropped = int((~keep).sum())
    out = df.loc[keep].reset_index(drop=True)
    print(
        f"Dropped {dropped} rows with null/invalid Weight "
        f"(kept {len(out)})"
    )
    return out


def to_date_hour_key(value) -> str:
    """
    "25-11-2025 08:00:17" → "25/11/2025|8 AM"
    Uses day-first parsing to match DD-MM-YYYY / DD/MM/YYYY VRN timestamps.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "nat"}:
        return ""
    ts = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if pd.isna(ts):
        return ""
    date_part = f"{int(ts.day):02d}/{int(ts.month):02d}/{int(ts.year)}"
    hour24 = int(ts.hour)
    hour12 = hour24 % 12
    if hour12 == 0:
        hour12 = 12
    ampm = "AM" if hour24 < 12 else "PM"
    return f"{date_part}|{hour12} {ampm}"


def to_date_key(value) -> str:
    """Normalize to DD/MM/YYYY (day-first). Empty if unparseable."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "nat"}:
        return ""
    ts = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if pd.isna(ts):
        return ""
    return f"{int(ts.day):02d}/{int(ts.month):02d}/{int(ts.year)}"


def _series_looks_date_only(series: pd.Series, sample_size: int = 200) -> bool:
    """True when values are mostly dates without a usable time component."""
    time_pat = re.compile(r"\d{1,2}:\d{2}")
    counted = 0
    with_time = 0
    for raw in series.head(sample_size).tolist():
        text = "" if raw is None else str(raw).strip()
        if not text or text.casefold() in {"nan", "none", "nat"}:
            continue
        counted += 1
        if time_pat.search(text):
            with_time += 1
    if counted == 0:
        return True
    return (with_time / counted) < 0.1


def load_vrn_from_folder(folder: Path, entity_name: str, config: dict) -> Path:
    """Merge local VRN Excel/CSV files using e10_config vrn_merge (no download)."""
    vrn_cfg = config.get("vrn_merge") or {}
    if not vrn_cfg.get("merge_columns"):
        raise RuntimeError("e10_config.json vrn_merge.merge_columns is empty.")

    vrn_mod = load_vrn_download_merge_module()
    paths = vrn_mod.list_local_files(folder)
    if not paths:
        raise FileNotFoundError(f"No VRN Excel/CSV files found under: {folder}")

    print(f"Local VRN folder: {folder}")
    print(f"Found {len(paths)} VRN file(s)")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    merged_name = f"{vrn_mod.safe_part(entity_name)}_local_merged_vrn.csv"
    merged_path = vrn_mod.merge_vrn_files(paths, vrn_cfg, OUTPUT_DIR / merged_name)
    print(f"VRN merge columns: {list((vrn_cfg.get('merge_columns') or {}).keys())}")
    return Path(merged_path)


def coalesce_vrn_datetime(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Ensure read_datetime is populated.
    - Prefer a combined datetime column when it already has time
    - Else combine date_part + time_part (DATE + TIME)
    - Else use date_part alone
    """
    result = df.copy()
    headers = [str(c) for c in result.columns]
    dt_col = resolve_column(
        headers,
        ["read_datetime", *(config.get("datetime_column_aliases") or [])],
    )
    date_col = resolve_column(headers, ["date_part", "DATE", "Date"])
    time_col = resolve_column(headers, ["time_part", "TIME", "Time"])

    out_col = "read_datetime"
    combined: list[str] = []

    n = len(result)
    dt_vals = (
        result[dt_col].tolist()
        if dt_col
        else [""] * n
    )
    date_vals = (
        result[date_col].tolist()
        if date_col
        else [""] * n
    )
    time_vals = (
        result[time_col].tolist()
        if time_col
        else [""] * n
    )

    used_combined = 0
    used_existing = 0
    used_date_only = 0

    for dt_raw, d_raw, t_raw in zip(dt_vals, date_vals, time_vals):
        dt_text = "" if dt_raw is None else str(dt_raw).strip()
        if dt_text.casefold() in {"", "nan", "none", "nat"}:
            dt_text = ""
        d_text = "" if d_raw is None else str(d_raw).strip()
        if d_text.casefold() in {"", "nan", "none", "nat"}:
            d_text = ""
        t_text = "" if t_raw is None else str(t_raw).strip()
        if t_text.casefold() in {"", "nan", "none", "nat"}:
            t_text = ""

        has_time_in_dt = bool(re.search(r"\d{1,2}:\d{2}", dt_text))
        if dt_text and has_time_in_dt:
            combined.append(dt_text)
            used_existing += 1
            continue
        if d_text and t_text:
            combined.append(f"{d_text} {t_text}")
            used_combined += 1
            continue
        if dt_text:
            combined.append(dt_text)
            used_date_only += 1
            continue
        if d_text:
            combined.append(d_text)
            used_date_only += 1
            continue
        combined.append("")

    result[out_col] = combined
    print(
        f"VRN datetime coalesce → {out_col!r}: "
        f"existing={used_existing}, DATE+TIME={used_combined}, "
        f"date-only={used_date_only} / {n}"
    )
    return result


def rename_vrn_lane_columns(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Rename merge keys (swb_wt_std_weight, …) to Power Query output names."""
    result = df.copy()
    lane_cfg = config.get("vrn_lane_columns") or {}
    for key, entry in lane_cfg.items():
        if not isinstance(entry, dict):
            continue
        out_name = str(entry.get("output") or "").strip()
        if not out_name:
            continue
        if key in result.columns and key != out_name:
            if out_name in result.columns:
                # Prefer non-empty from key into out_name
                result[out_name] = result[out_name].where(
                    result[out_name].astype(str).str.strip().ne(""),
                    result[key],
                )
                result = result.drop(columns=[key])
            else:
                result = result.rename(columns={key: out_name})
        elif key not in result.columns:
            aliases = list(entry.get("aliases") or []) + [out_name, key]
            src = resolve_column([str(c) for c in result.columns], aliases)
            if src and src != out_name:
                result[out_name] = result[src]
    return result


def date_range_from_vrn_df(vrn_df: pd.DataFrame, config: dict) -> tuple[str, str]:
    """
    Min/max calendar dates from VRN DATE column (values like 01/07/2026).
    Returns ISO strings YYYY-MM-DD for ETC download.
    """
    headers = [str(c) for c in vrn_df.columns]
    date_col = resolve_column(
        headers,
        (config.get("datetime_column_aliases") or [])
        + ["DATE", "Date", "read_datetime", "Date & Time"],
    )
    if not date_col:
        raise RuntimeError(
            "DATE / datetime column not found on VRN for ETC date range. "
            f"Available: {list(vrn_df.columns)}"
        )

    parsed = pd.to_datetime(vrn_df[date_col], dayfirst=True, errors="coerce")
    valid = parsed.dropna()
    if valid.empty:
        raise RuntimeError(
            f"Could not parse any dates from VRN column {date_col!r} "
            f"(expected e.g. 01/07/2026)."
        )

    start = valid.min().date()
    end = valid.max().date()
    print(
        f"VRN date range from {date_col!r}: "
        f"{start.isoformat()} → {end.isoformat()} "
        f"({len(valid):,} dated rows)"
    )
    return start.isoformat(), end.isoformat()


def run_etc_download_merge(
    entity_name: str,
    from_date: str,
    to_date: str,
    config: dict,
) -> Path:
    """
    Download ETC from submissions (Source_DB) and merge using e10 etc_merge config.
    Keeps merge_columns from config (Net Settlement Amount, NPCI Class, + join keys).
    """
    etc_cfg = config.get("etc_merge") or {}
    if not etc_cfg.get("merge_columns"):
        raise RuntimeError("e10_config.json etc_merge.merge_columns is empty.")

    load_env()
    etc_mod = load_etc_download_merge_module()
    etc_mod.load_env = load_env
    start, end = etc_mod.validate_interval(from_date, to_date)

    download_folder = ETC_DOWNLOAD_FOLDER
    download_folder.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(
        f"ETC source DB: {require_env('DB_NAME')} "
        f"table={os.getenv('Table_NAME', 'submissions')}"
    )
    print("Connecting to DB for ETC download…")
    with psycopg2.connect(**etc_mod.connection_kwargs()) as conn:
        local_paths, _stats = etc_mod.download_etc_files(
            conn,
            entity_name=entity_name,
            start=start,
            end=end,
            output_folder=download_folder,
            skip_existing=True,
        )

    paths = local_paths or etc_mod.list_local_etc_files(
        download_folder / etc_mod.safe_part(entity_name)
    )
    if not paths:
        paths = etc_mod.list_local_etc_files(download_folder)
    if not paths:
        raise FileNotFoundError(
            f"No ETC files downloaded for entity={entity_name!r} "
            f"range {start.isoformat()} → {end.isoformat()}"
        )

    merged_name = (
        f"{etc_mod.safe_part(entity_name)}_"
        f"{start.isoformat()}_{end.isoformat()}_merged_etc.csv"
    )
    merged_path = etc_mod.merge_etc_files(
        paths,
        etc_cfg,
        OUTPUT_DIR / merged_name,
    )
    etc_mod.delete_downloaded_files(paths, download_folder)

    # Also write the stable E10 output name
    final_path = Path(ETC_OUTPUT_FILE)
    if not final_path.is_absolute():
        final_path = BASE_DIR / final_path
    final_path.parent.mkdir(parents=True, exist_ok=True)
    pd.read_csv(merged_path, dtype=str, keep_default_na=False).to_csv(
        final_path, index=False, encoding="utf-8-sig"
    )
    print(f"ETC merge columns: {list((etc_cfg.get('merge_columns') or {}).keys())}")
    print(f"Wrote ETC output: {final_path}")
    return final_path


def merge_vrn_with_etc(
    vrn_df: pd.DataFrame,
    etc_df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    Left-join ETC onto VRN on normalized vehicle + date key.
    When VRN DATE is date-only (e.g. 01/07/2026), join on calendar date.
    Otherwise join on date/hour key.
    Brings net_settlement_amt and npci_class from ETC.
    """
    headers = [str(c) for c in vrn_df.columns]
    vrn_veh_col = resolve_column(headers, config.get("vehicle_column_aliases") or [])
    vrn_dt_col = resolve_column(
        headers,
        (config.get("datetime_column_aliases") or []) + ["DATE", "read_datetime"],
    )
    if not vrn_veh_col:
        raise RuntimeError(
            "Vehicle column not found on VRN for ETC join. "
            f"Available: {list(vrn_df.columns)}"
        )
    if not vrn_dt_col:
        raise RuntimeError(
            "Datetime column not found on VRN for ETC join. "
            f"Available: {list(vrn_df.columns)}"
        )

    etc_headers = [str(c) for c in etc_df.columns]
    etc_veh_col = resolve_column(
        etc_headers,
        ["vehicle_reg_no", *(config.get("vehicle_column_aliases") or [])],
    )
    etc_dt_col = resolve_column(
        etc_headers,
        ["read_datetime", *(config.get("datetime_column_aliases") or [])],
    )
    if not etc_veh_col or not etc_dt_col:
        raise RuntimeError(
            "ETC missing vehicle_reg_no / read_datetime for join. "
            f"Available: {list(etc_df.columns)}"
        )

    settle_col = resolve_column(
        etc_headers,
        ["net_settlement_amt", "Net Settlement Amt", "Net Settlement Amount"],
    )
    npci_col = resolve_column(
        etc_headers,
        ["npci_class", "NPCI Class Desc", "NPCI Class"],
    )
    if not settle_col or not npci_col:
        raise RuntimeError(
            "ETC missing net_settlement_amt / npci_class. "
            f"Available: {list(etc_df.columns)}"
        )

    date_only = _series_looks_date_only(vrn_df[vrn_dt_col])
    left = vrn_df.copy()
    left["_join_veh"] = left[vrn_veh_col].map(normalize_vehicle_number)

    right = etc_df.copy()
    right["_join_veh"] = right[etc_veh_col].map(normalize_vehicle_number)

    if date_only:
        left["date_key"] = left[vrn_dt_col].map(to_date_key)
        right["_join_date"] = right[etc_dt_col].map(to_date_key)
        bring = (
            right.loc[
                right["_join_veh"].ne("") & right["_join_date"].ne(""),
                ["_join_veh", "_join_date", settle_col, npci_col],
            ]
            .drop_duplicates(subset=["_join_veh", "_join_date"], keep="first")
            .rename(
                columns={
                    "_join_date": "date_key",
                    settle_col: "Net Settlement Amount",
                    npci_col: "NPCI Class",
                }
            )
        )
        merged = left.merge(
            bring,
            on=["_join_veh", "date_key"],
            how="left",
        ).drop(columns=["_join_veh"])
        join_desc = f"vehicle + date ({vrn_dt_col!r} date-only)"
    else:
        left["date_hour_key"] = left[vrn_dt_col].map(to_date_hour_key)
        right["_join_dh"] = right[etc_dt_col].map(to_date_hour_key)
        bring = (
            right.loc[
                right["_join_veh"].ne("") & right["_join_dh"].ne(""),
                ["_join_veh", "_join_dh", settle_col, npci_col],
            ]
            .drop_duplicates(subset=["_join_veh", "_join_dh"], keep="first")
            .rename(
                columns={
                    "_join_dh": "date_hour_key",
                    settle_col: "Net Settlement Amount",
                    npci_col: "NPCI Class",
                }
            )
        )
        merged = left.merge(
            bring,
            on=["_join_veh", "date_hour_key"],
            how="left",
        ).drop(columns=["_join_veh"])
        join_desc = f"vehicle + date/hour ({vrn_dt_col!r})"

    matched = int(
        merged["Net Settlement Amount"].fillna("").astype(str).str.strip().ne("").sum()
    )
    print(
        f"VRN↔ETC join on {join_desc} "
        f"↔ {etc_veh_col!r} / {etc_dt_col!r}: "
        f"{matched}/{len(merged)} rows matched"
    )
    return merged


def _parse_weight_number(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text.casefold() in {"nan", "none", "nat", "n/a", "na", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def weight_to_range_label(weight_value, config: dict) -> str:
    """Map numeric weight → Custom band label using e10_config weight_ranges."""
    weight = _parse_weight_number(weight_value)
    if weight is None:
        return ""

    ranges = config.get("weight_ranges") or []
    if not ranges:
        raise RuntimeError("e10_config.json weight_ranges is empty.")

    for entry in ranges:
        try:
            max_w = float(entry.get("max_weight"))
        except (TypeError, ValueError):
            continue
        label = str(entry.get("label") or "").strip()
        if weight <= max_w:
            return label

    return str(config.get("weight_range_above_max_label") or "").strip()


def add_weight_range_column(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Add Custom (or configured) column from Weight using config weight_ranges."""
    headers = [str(c) for c in df.columns]
    weight_col = resolve_column(
        headers,
        [
            str(config.get("weight_output_column") or "Weight"),
            "Weight",
            "weight",
        ],
    )
    if not weight_col:
        raise RuntimeError(
            "Weight column not found for weight-range banding. "
            f"Available: {list(df.columns)}"
        )

    out_col = (
        str(config.get("weight_range_output_column") or "Custom").strip() or "Custom"
    )
    result = df.copy()
    labels = [weight_to_range_label(v, config) for v in result[weight_col].tolist()]
    result[out_col] = labels
    filled = sum(1 for v in labels if v)
    print(
        f"Weight range column {out_col!r} from {weight_col!r}: "
        f"{filled}/{len(result)} rows labeled"
    )
    return result


def _norm_weight_join_key(value) -> str:
    """Normalize weight for lookup (7500 / 7500.0 → '7500')."""
    num = _parse_weight_number(value)
    if num is None:
        return ""
    if float(num).is_integer():
        return str(int(num))
    return str(num)


def _clean_weight_group_join_key(value) -> str:
    """PQ: remove 'Kgs' then spaces from Weight Group before sheet join."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "nat"}:
        return ""
    text = re.sub(r"(?i)kgs", "", text)
    text = re.sub(r"\s+", "", text)
    return text.casefold()


def _norm_npci_key(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().casefold()
    text = re.sub(r"[\s_\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in {"", "nan", "none", "nat"}:
        return ""
    return text


def _npci_matches(npci_raw, aliases: list) -> bool:
    key = _norm_npci_key(npci_raw)
    if not key:
        return False
    for alias in aliases or []:
        alias_key = _norm_npci_key(alias)
        if not alias_key:
            continue
        if key == alias_key or alias_key in key or key in alias_key:
            return True
    return False


def weight_to_weight_group(
    weight_value,
    npci_value,
    config: dict,
) -> str:
    """E10.txt lines 53–67 — map weight (+ NPCI when needed) → Weight Group."""
    weight = _parse_weight_number(weight_value)
    if weight is None:
        return ""

    for rule in config.get("weight_group_rules") or []:
        rule_type = str(rule.get("type") or "").strip().casefold()
        label = str(rule.get("label") or "").strip()
        if not label:
            continue

        npci_any = list(rule.get("npci_any") or [])
        if npci_any and not _npci_matches(npci_value, npci_any):
            continue

        try:
            if rule_type == "eq":
                if weight == float(rule["weight"]):
                    return label
            elif rule_type == "lt":
                if weight < float(rule["weight"]):
                    return label
            elif rule_type == "gt":
                if weight > float(rule["weight"]):
                    return label
            elif rule_type == "between":
                gt = float(rule["gt"])
                lt = float(rule["lt"])
                if weight > gt and weight < lt:
                    return label
        except (KeyError, TypeError, ValueError):
            continue

    return ""


def add_weight_group_column(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Add Weight Group from stage-2 rules; drop rows with null/empty group."""
    if not (config.get("weight_group_rules") or []):
        raise RuntimeError("e10_config.json weight_group_rules is empty.")

    headers = [str(c) for c in df.columns]
    weight_col = resolve_column(
        headers,
        [
            str(config.get("weight_output_column") or "Weight"),
            "Weight",
            "weight",
        ],
    )
    if not weight_col:
        raise RuntimeError(
            "Weight column not found for Weight Group. "
            f"Available: {list(df.columns)}"
        )

    npci_col = resolve_column(
        headers,
        [
            "NPCI Class",
            "NPCI Class Desc",
            "npci_class",
            "NPCI CLass",
        ],
    )

    out_col = (
        str(config.get("weight_group_output_column") or "Weight Group").strip()
        or "Weight Group"
    )
    result = df.copy()
    npci_series = (
        result[npci_col].tolist()
        if npci_col
        else [""] * len(result)
    )
    groups = [
        weight_to_weight_group(w, n, config)
        for w, n in zip(result[weight_col].tolist(), npci_series)
    ]
    result[out_col] = groups

    keep = result[out_col].astype(str).str.strip().ne("")
    dropped = int((~keep).sum())
    result = result.loc[keep].reset_index(drop=True)
    print(
        f"Weight Group on {weight_col!r}"
        + (f" (+ {npci_col!r})" if npci_col else "")
        + f" -> {out_col!r}: kept {len(result)}, dropped null group {dropped}"
    )
    return result


def _load_std_weight_tables(config: dict) -> tuple[dict[str, str], dict[str, str]]:
    """
    From OW multiple LSW std weights.xlsx:
      by_weight[weight_key] → Std Weight
      by_group[cleaned Weight Group] → Std Weight
    """
    cfg = config.get("std_weight_lookup") or {}
    file_name = str(cfg.get("file") or "OW multiple LSW std weights.xlsx").strip()
    path = Path(file_name)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.is_file():
        raise FileNotFoundError(f"Std weight lookup file not found: {path}")

    sheet = cfg.get("sheet")
    df = pd.read_excel(
        path,
        sheet_name=0 if not sheet else sheet,
        dtype=str,
    )
    if isinstance(df, dict):
        df = next(iter(df.values()))

    headers = [str(c) for c in df.columns]
    weight_col = resolve_column(
        headers,
        [str(cfg.get("weight_column") or "Weight"), "Weight"],
    )
    range_col = resolve_column(
        headers,
        [
            str(cfg.get("weight_range_column") or "Weight Group"),
            "Weight Group",
        ],
    )
    std_col = resolve_column(
        headers,
        [str(cfg.get("std_weight_column") or "Std Weight"), "Std Weight"],
    )
    if not weight_col or not std_col:
        raise RuntimeError(
            "Std weight file missing Weight / Std Weight. "
            f"Available: {list(df.columns)}"
        )

    by_weight: dict[str, str] = {}
    by_group: dict[str, str] = {}
    for idx in range(len(df)):
        std_raw = df[std_col].iloc[idx]
        std_text = (
            ""
            if std_raw is None or (isinstance(std_raw, float) and pd.isna(std_raw))
            else str(std_raw).strip()
        )
        if not std_text or std_text.casefold() in {"nan", "none"}:
            continue

        w_key = _norm_weight_join_key(df[weight_col].iloc[idx])
        if w_key and w_key not in by_weight:
            by_weight[w_key] = std_text

        if range_col:
            g_raw = df[range_col].iloc[idx]
            g_key = _clean_weight_group_join_key(g_raw)
            if g_key and g_key not in by_group:
                by_group[g_key] = std_text
            # Also index raw-ish normalized form
            if g_raw is not None and not (isinstance(g_raw, float) and pd.isna(g_raw)):
                raw_key = re.sub(r"\s+", " ", str(g_raw).strip()).casefold()
                if raw_key and raw_key not in by_group:
                    by_group[raw_key] = std_text

    print(
        f"Loaded std-weight lookup from {path.name}: "
        f"{len(by_weight)} by Weight, {len(by_group)} by Weight Group"
    )
    return by_weight, by_group


def _is_numeric_std_token(value) -> bool:
    """True when Weight Group already holds a std-weight number (exact-weight path)."""
    num = _parse_weight_number(value)
    if num is None:
        return False
    text = str(value).strip()
    # Reject range labels that happen to parse partially
    if any(ch.isalpha() for ch in text):
        return False
    if "<" in text or ">" in text:
        return False
    return True


def attach_std_weight_from_lookup(
    df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    After Weight Group is set (E10.txt):
      1) Join sheet on cleaned Weight Group → Std Weight
      2) Also try match on Weight
      3) If Weight Group is already a number (exact path), use it when sheet misses
      4) Else keep original Weight
    Writes Std Weight (Power Query name). Falls back to Weight when no match.
    """
    cfg = config.get("std_weight_lookup") or {}
    headers = [str(c) for c in df.columns]
    weight_col = resolve_column(
        headers,
        [
            str(config.get("weight_output_column") or "Weight"),
            "Weight",
            "weight",
        ],
    )
    group_col = resolve_column(
        headers,
        [
            str(config.get("weight_group_output_column") or "Weight Group"),
            "Weight Group",
        ],
    )
    if not weight_col or not group_col:
        raise RuntimeError(
            "Need Weight and Weight Group for std-weight lookup. "
            f"Available: {list(df.columns)}"
        )

    out_col = str(cfg.get("output_column") or "Std Weight").strip() or "Std Weight"
    by_weight, by_group = _load_std_weight_tables(config)

    originals: list[str] = []
    matched_group = 0
    matched_weight = 0
    matched_exact_token = 0
    fallback = 0

    for w_raw, g_raw in zip(df[weight_col].tolist(), df[group_col].tolist()):
        g_text = "" if g_raw is None else str(g_raw).strip()
        std = None
        source = ""

        # 1) Sheet join on cleaned Weight Group (PQ Merged Queries1)
        g_key = _clean_weight_group_join_key(g_text)
        if g_key and g_key in by_group:
            std = by_group[g_key]
            source = "group"
        else:
            raw_key = re.sub(r"\s+", " ", g_text).casefold() if g_text else ""
            if raw_key and raw_key in by_group:
                std = by_group[raw_key]
                source = "group"

        # 2) Sheet join on Weight (helps when group label text differs slightly)
        if not std:
            w_key = _norm_weight_join_key(w_raw)
            if w_key and w_key in by_weight:
                std = by_weight[w_key]
                source = "weight"

        # 3) Exact-weight path: Weight Group already stores std (e.g. "7875")
        if not std and _is_numeric_std_token(g_text):
            std = _norm_weight_join_key(g_text) or g_text
            source = "exact_token"

        # 4) Fallback — keep checkpost weight
        if not std:
            std = "" if w_raw is None else str(w_raw).strip()
            source = "fallback"

        originals.append(std)
        if source == "group":
            matched_group += 1
        elif source == "weight":
            matched_weight += 1
        elif source == "exact_token":
            matched_exact_token += 1
        else:
            fallback += 1

    result = df.copy()
    result[out_col] = originals
    print(
        f"Std Weight lookup: group={matched_group}, "
        f"weight={matched_weight}, exact_token={matched_exact_token}, "
        f"fallback={fallback} / {len(result)}"
    )
    return result


def _normalize_custom_label_key(value) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\u00a0", " ").strip().casefold()
    text = text.replace(",", "")
    return " ".join(text.split())


def build_custom_to_class_index(config: dict) -> dict[str, int]:
    """
    Map Custom weight-band labels → vehicle-class indexes.
    Ordered weight_ranges align with WEIGHT_RANGE_INDEXES (1..N);
    above-max label → OSV = 6.
    """
    ranges = config.get("weight_ranges") or []
    indexes = list(WEIGHT_RANGE_INDEXES)
    if not ranges:
        raise RuntimeError("e10_config.json weight_ranges is empty.")
    if len(ranges) > len(indexes):
        raise RuntimeError(
            f"weight_ranges has {len(ranges)} bands but vehicle-class "
            f"WEIGHT_RANGE_INDEXES has only {len(indexes)} indexes."
        )

    lookup: dict[str, int] = {}
    for i, entry in enumerate(ranges):
        label = str(entry.get("label") or "").strip()
        idx = int(indexes[i][1])
        key = _normalize_custom_label_key(label)
        if key:
            lookup[key] = idx

    above = str(config.get("weight_range_above_max_label") or ">60,000 Kgs").strip()
    above_key = _normalize_custom_label_key(above)
    if above_key:
        lookup[above_key] = 6  # OSV
    return lookup


def parse_rate_cutover_date(config: dict) -> date:
    """First day when Plaza_Rates_Apr26_onwards applies (default: after April 2026)."""
    raw = str(config.get("rate_cutover_date") or "2026-05-01").strip()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid rate_cutover_date: {raw!r}") from exc


def select_plaza_rates_book(read_d: date, cutover: date) -> dict:
    if read_d < cutover:
        return PLAZA_RATES
    return Plaza_Rates_Apr26_onwards


def lookup_single_rate(
    entity_name: str,
    rates_book: dict,
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
    journey_rates = plaza.get("single") if isinstance(plaza, dict) else None
    if not isinstance(journey_rates, dict):
        raise RuntimeError(f"No 'single' rates for entity {entity_name!r}")
    if class_index not in journey_rates:
        raise RuntimeError(
            f"No single rate for class index {class_index} on entity {entity_name!r}"
        )
    return float(journey_rates[class_index])


def apply_applicable_rates_from_custom(
    df: pd.DataFrame,
    config: dict,
    entity_name: str,
) -> pd.DataFrame:
    """
    Custom weight band → vehicle-class index → plaza single rate → Applicable Rate.
    Rate book: PLAZA_RATES until day before cutover; Plaza_Rates_Apr26_onwards after.
    """
    if df is None or df.empty:
        return df

    headers = [str(c) for c in df.columns]
    custom_col = resolve_column(
        headers,
        [
            str(config.get("weight_range_output_column") or "Custom"),
            "Custom",
        ],
    )
    dt_col = resolve_column(
        headers,
        (config.get("datetime_column_aliases") or []) + ["read_datetime"],
    )
    if not custom_col:
        raise RuntimeError(
            f"Custom column not found for rate lookup. Available: {list(df.columns)}"
        )
    if not dt_col:
        raise RuntimeError(
            f"read_datetime column not found for rate cutover. "
            f"Available: {list(df.columns)}"
        )

    index_col = str(config.get("class_index_output_column") or "Class Index").strip()
    if not index_col:
        index_col = "Class Index"
    rate_col = str(config.get("applicable_rate_output") or "Applicable Rate").strip()
    if not rate_col:
        rate_col = "Applicable Rate"

    custom_to_index = build_custom_to_class_index(config)
    cutover = parse_rate_cutover_date(config)
    parsed_dt = pd.to_datetime(df[dt_col], errors="coerce", dayfirst=True)

    class_indexes: list[str] = []
    rates: list[str] = []
    missing_custom = 0
    missing_date = 0
    used_default_book = 0
    used_apr26_book = 0

    for custom_raw, dt_val in zip(df[custom_col].tolist(), parsed_dt.tolist()):
        custom_key = _normalize_custom_label_key(custom_raw)
        class_index = custom_to_index.get(custom_key) if custom_key else None
        if class_index is None:
            missing_custom += 1
            class_indexes.append("")
            rates.append("")
            continue

        if pd.isna(dt_val):
            missing_date += 1
            class_indexes.append(str(class_index))
            rates.append("")
            continue

        if isinstance(dt_val, datetime):
            read_d = dt_val.date()
        elif isinstance(dt_val, date):
            read_d = dt_val
        else:
            read_d = pd.Timestamp(dt_val).date()

        rates_book = select_plaza_rates_book(read_d, cutover)
        if rates_book is Plaza_Rates_Apr26_onwards:
            used_apr26_book += 1
        else:
            used_default_book += 1

        rate = lookup_single_rate(entity_name, rates_book, int(class_index))
        class_indexes.append(str(class_index))
        rates.append(str(rate))

    result = df.copy()
    result[index_col] = class_indexes
    result[rate_col] = rates

    filled = sum(1 for v in rates if str(v).strip())
    print(
        f"Applicable Rate (single) for entity {entity_name!r}: "
        f"{filled}/{len(result)} filled | "
        f"PLAZA_RATES={used_default_book}, Apr26_onwards={used_apr26_book} "
        f"(cutover={cutover.isoformat()}) | "
        f"unknown Custom={missing_custom}, missing date={missing_date}"
    )
    if missing_custom:
        unknown = sorted(
            {
                str(v).strip()
                for v in df[custom_col].tolist()
                if _normalize_custom_label_key(v) not in custom_to_index
                and str(v).strip()
            }
        )
        print(f"  Unknown Custom labels (sample): {unknown[:10]}")
    return result


def _amount_is_zero(value) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True
    text = str(value).strip().replace(",", "")
    if text == "" or text.casefold() in {"nan", "none", "nat"}:
        return True
    try:
        return abs(float(text)) < 1e-9
    except ValueError:
        return False


def apply_overweight_and_filters(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    E10.txt after Std Weight (April / Custom<=7500 filters intentionally skipped):
      - SWB Wt/Std. Weight null → 0; drop empty SWB
      - Overweight = SWB - Std if SWB > 0 else Lane Weight - Std
      - Overweight % = Overweight / Std * 100
      - Keep Overweight > 0
      - Keep LANE OVERLOAD AMT = 0 and SWB AMT = 0
      - OW Status from Lane/Chg Standard Weight vs Std Weight + SWB
    """
    if df is None or df.empty:
        return df

    headers = [str(c) for c in df.columns]
    lane_cfg = config.get("vrn_lane_columns") or {}

    def _aliases(key: str, *extra: str) -> list[str]:
        entry = lane_cfg.get(key) or {}
        out = [str(entry.get("output") or "").strip()] if entry.get("output") else []
        out.extend(str(a) for a in (entry.get("aliases") or []))
        out.extend(extra)
        out.append(key)
        return [a for a in out if a]

    swb_col = resolve_column(headers, _aliases("swb_wt_std_weight", "SWB Wt/Std. Weight"))
    lane_w_col = resolve_column(headers, _aliases("lane_weight", "Lane Weight"))
    lane_std_col = resolve_column(
        headers, _aliases("lane_chg_standard_weight", "Lane/Chg Standard Weight")
    )
    overload_col = resolve_column(
        headers, _aliases("lane_overload_amt", "LANE OVERLOAD AMT", "OVERLOAD AMT")
    )
    swb_amt_col = resolve_column(headers, _aliases("swb_amt", "SWB AMT"))
    std_col = resolve_column(
        headers,
        [
            str((config.get("std_weight_lookup") or {}).get("output_column") or "Std Weight"),
            "Std Weight",
        ],
    )

    missing = [
        name
        for name, col in [
            ("SWB Wt/Std. Weight", swb_col),
            ("Lane Weight", lane_w_col),
            ("Lane/Chg Standard Weight", lane_std_col),
            ("LANE OVERLOAD AMT", overload_col),
            ("SWB AMT", swb_amt_col),
            ("Std Weight", std_col),
        ]
        if not col
    ]
    if missing:
        raise RuntimeError(
            f"Missing columns for overweight pipeline: {missing}. "
            f"Available: {list(df.columns)}"
        )

    work = df.copy()
    # PQ: null SWB → 0
    swb_num = work[swb_col].map(_parse_weight_number)
    work[swb_col] = swb_num.map(lambda v: 0.0 if v is None else float(v))
    before = len(work)
    # PQ: keep SWB not null / not "" (after fill, all numeric remain)
    work = work.loc[work[swb_col].notna()].copy()
    print(f"SWB Wt/Std. Weight null→0; kept {len(work)}/{before} rows")

    lane_num = work[lane_w_col].map(_parse_weight_number)
    std_num = work[std_col].map(_parse_weight_number)

    overweight: list[float | None] = []
    overweight_pct: list[float | None] = []
    for swb, lane_w, std in zip(
        work[swb_col].tolist(), lane_num.tolist(), std_num.tolist()
    ):
        swb_v = float(swb) if swb is not None and not pd.isna(swb) else None
        if std is None or std == 0:
            overweight.append(None)
            overweight_pct.append(None)
            continue
        if swb_v is not None and swb_v > 0:
            ow = swb_v - float(std)
        else:
            if lane_w is None:
                overweight.append(None)
                overweight_pct.append(None)
                continue
            ow = float(lane_w) - float(std)
        overweight.append(round(ow, 4))
        overweight_pct.append(round((ow / float(std)) * 100.0, 2))

    work["Overweight"] = overweight
    work["Overweight %"] = overweight_pct

    before = len(work)
    ow_ok = work["Overweight"].map(
        lambda v: v is not None and not pd.isna(v) and float(v) > 0
    )
    work = work.loc[ow_ok].copy()
    print(f"Filtered Overweight > 0: kept {len(work)}/{before}")

    before = len(work)
    overload_zero = work[overload_col].map(_amount_is_zero)
    swb_amt_zero = work[swb_amt_col].map(_amount_is_zero)
    work = work.loc[overload_zero & swb_amt_zero].copy()
    print(
        f"Filtered LANE OVERLOAD AMT=0 and SWB AMT=0: "
        f"kept {len(work)}/{before}"
    )

    status: list[str] = []
    for lane_std_raw, std_raw, swb_raw in zip(
        work[lane_std_col].tolist(),
        work[std_col].tolist(),
        work[swb_col].tolist(),
    ):
        lane_std = _parse_weight_number(lane_std_raw)
        std = _parse_weight_number(std_raw)
        swb = _parse_weight_number(swb_raw)
        if lane_std is not None and std is not None and abs(lane_std - std) < 1e-6:
            if swb is None or abs(swb) < 1e-9:
                status.append("OW At WIM")
            else:
                status.append("Not Charged At SWB")
        else:
            status.append("Altered at WIM/SWB")
    work["OW Status"] = status

    print(
        f"OW Status counts: "
        f"{work['OW Status'].value_counts(dropna=False).to_dict()}"
    )
    return work.reset_index(drop=True)


def save_output(df: pd.DataFrame, path: Path) -> Path:
    path = Path(path)
    if not path.is_absolute():
        path = BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".xlsx":
        df.to_excel(path, index=False)
    else:
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"Wrote: {path}")
    return path


def main() -> int:
    print("=" * 60)
    print("E10 — Local VRN + Weight + ETC + Overweight + Applicable Rate")
    print("=" * 60)

    load_env()
    config = load_config()
    entity_name = resolve_entity_name()
    vrn_folder = resolve_vrn_input_folder()
    print(f"entity_name: {entity_name}")
    print(f"VRN_INPUT_FOLDER: {vrn_folder}")

    print("-" * 60)
    print("Loading / merging local VRN…")
    vrn_path = load_vrn_from_folder(vrn_folder, entity_name, config)
    print(f"Merged VRN: {vrn_path}")

    vrn_df = pd.read_csv(vrn_path, dtype=str, keep_default_na=False)
    vrn_df = coalesce_vrn_datetime(vrn_df, config)
    vrn_df = rename_vrn_lane_columns(vrn_df, config)
    print(f"Merged VRN rows: {len(vrn_df)}")
    print(f"Merged VRN columns: {list(vrn_df.columns)}")

    from_date, to_date = date_range_from_vrn_df(vrn_df, config)
    print(f"ETC download date range: {from_date} → {to_date}")

    print("-" * 60)
    filtered = drop_excluded_tc_class_rows(vrn_df, config)

    print("-" * 60)
    with_weight = attach_weight_from_checkpost(filtered, config)
    with_weight = drop_invalid_weight_rows(with_weight, config)

    vrn_out = save_output(with_weight, Path(VRN_OUTPUT_FILE))
    print(f"VRN rows: {len(with_weight)} | Columns: {list(with_weight.columns)}")
    print(f"VRN output: {vrn_out}")

    print("-" * 60)
    print("Downloading / merging ETC…")
    etc_out = run_etc_download_merge(entity_name, from_date, to_date, config)
    etc_df = pd.read_csv(etc_out, dtype=str, keep_default_na=False)
    print(f"ETC rows: {len(etc_df)} | Columns: {list(etc_df.columns)}")
    print(f"ETC output: {etc_out}")

    print("-" * 60)
    print("Joining VRN ↔ ETC on vehicle + date/time…")
    merged = merge_vrn_with_etc(with_weight, etc_df, config)

    print("-" * 60)
    print("Adding Custom weight-range band…")
    merged = add_weight_range_column(merged, config)

    print("-" * 60)
    print("Adding Weight Group (stage-2 rules)…")
    merged = add_weight_group_column(merged, config)

    print("-" * 60)
    print("Looking up Std Weight…")
    merged = attach_std_weight_from_lookup(merged, config)

    print("-" * 60)
    print("Applying Applicable Rate (Custom → class index → single rates)…")
    merged = apply_applicable_rates_from_custom(merged, config, entity_name)

    print("-" * 60)
    print("Overweight / filters / OW Status…")
    merged = apply_overweight_and_filters(merged, config)

    # Drop helper date/time parts from final export if present
    drop_helpers = [
        c for c in ("date_part", "time_part") if c in merged.columns
    ]
    if drop_helpers:
        merged = merged.drop(columns=drop_helpers)

    merged_out = save_output(merged, Path(MERGED_VRN_ETC_OUTPUT_FILE))
    print(f"Merged rows: {len(merged)} | Columns: {list(merged.columns)}")
    print(f"Merged output: {merged_out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
