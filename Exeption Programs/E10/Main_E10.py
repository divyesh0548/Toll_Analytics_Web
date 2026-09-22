"""
E10 — VRN + checkpost Weight, then ETC download/merge, then VRN↔ETC join.

1) Download/merge VRN (vehicle_reg_no, tc_class, read_datetime from e10_config)
2) Drop rows whose TC Class is in the exclude list
3) Lookup weight from Checkpost DB by Unique Vehicle Number
4) Drop rows with null / empty / "0" / "N/A" Weight
5) Download/merge ETC (vehicle, datetime, Net Settlement, NPCI Class)
6) Join VRN↔ETC on normalized vehicle + date/hour key
7) Add Custom weight-range band from Weight (ranges in e10_config.json)
8) Add Weight Group (E10.txt stage-2 rules), drop null groups, lookup Std Weight
9) Map Custom → vehicle-class index → plaza single rate (Applicable Rate);
   rates book switches on read_datetime after April 2026

DB credentials:
  Website/backend/.env — Source_DB_NAME + exceptions_Table_NAME → submissions (VRN + ETC)
  E4/.env — Checkpost_DB_NAME + Checkpost_Table_NAME → checkpost weights
  (aliases CHECKPOST_DB / CHECKPOST_TABLE also accepted)

Run:
  1. Set ENTITY_NAME, FROM_DATE, TO_DATE
  2. python Main_E10.py
     or: python Main_E10.py odhaki_paipkhar 2026-01-01 2026-04-30
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
OUTPUT_DIR = BASE_DIR / "output"
ETC_DOWNLOAD_FOLDER = BASE_DIR / "etc_downloads"

# Plaza rates (E4)
if str(E4_DIR) not in sys.path:
    sys.path.insert(0, str(E4_DIR))
from plaza_rates import PLAZA_RATES, Plaza_Rates_Apr26_onwards  # noqa: E402


def _load_vehicle_class_module():
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
ENTITY_NAME = "odhaki_paipkhar"
FROM_DATE = "2026-01-01"
TO_DATE = "2026-01-01"
VRN_OUTPUT_FILE = OUTPUT_DIR / "e10_vrn_with_weight.csv"
ETC_OUTPUT_FILE = OUTPUT_DIR / "e10_merged_etc.csv"
MERGED_VRN_ETC_OUTPUT_FILE = OUTPUT_DIR / "e10_vrn_etc_merged.csv"
VRN_DOWNLOAD_FOLDER = BASE_DIR / "vrn_downloads"


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


def resolve_entity_and_dates() -> tuple[str, str, str]:
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
        entity = input("Enter entity_name: ").strip()
    if not from_date:
        from_date = input("Enter FROM_DATE (YYYY-MM-DD): ").strip()
    if not to_date:
        to_date = input("Enter TO_DATE (YYYY-MM-DD): ").strip()
    if not entity or not from_date or not to_date:
        raise RuntimeError("entity_name, FROM_DATE and TO_DATE are required.")
    return entity, from_date, to_date


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
    Uses day-first parsing to match DD-MM-YYYY VRN/ETC timestamps.
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


def run_vrn_download_merge(
    entity_name: str,
    from_date: str,
    to_date: str,
    config: dict,
) -> Path:
    """Download VRN files and merge using e10_config vrn_merge (incl. datetime)."""
    vrn_cfg = config.get("vrn_merge") or {}
    if not vrn_cfg.get("merge_columns"):
        raise RuntimeError("e10_config.json vrn_merge.merge_columns is empty.")

    load_env()
    vrn_mod = load_vrn_download_merge_module()
    vrn_mod.load_env = load_env
    start, end = vrn_mod.validate_interval(from_date, to_date)

    download_folder = VRN_DOWNLOAD_FOLDER
    download_folder.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(
        f"VRN source DB: {require_env('DB_NAME')} "
        f"table={os.getenv('Table_NAME', 'submissions')}"
    )
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
        OUTPUT_DIR / merged_name,
    )
    vrn_mod.delete_downloaded_files(paths, download_folder)
    print(f"VRN merge columns: {list((vrn_cfg.get('merge_columns') or {}).keys())}")
    return Path(merged_path)


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
    Left-join ETC onto VRN on normalized vehicle + date/hour key.
    Brings net_settlement_amt and npci_class from ETC.
    """
    headers = [str(c) for c in vrn_df.columns]
    vrn_veh_col = resolve_column(headers, config.get("vehicle_column_aliases") or [])
    vrn_dt_col = resolve_column(
        headers,
        (config.get("datetime_column_aliases") or []) + ["read_datetime"],
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

    left = vrn_df.copy()
    left["_join_veh"] = left[vrn_veh_col].map(normalize_vehicle_number)
    left["date_hour_key"] = left[vrn_dt_col].map(to_date_hour_key)

    right = etc_df.copy()
    right["_join_veh"] = right[etc_veh_col].map(normalize_vehicle_number)
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

    matched = int(
        merged["Net Settlement Amount"].fillna("").astype(str).str.strip().ne("").sum()
    )
    print(
        f"VRN↔ETC join on vehicle + date/hour "
        f"({vrn_veh_col!r} / {vrn_dt_col!r} ↔ {etc_veh_col!r} / {etc_dt_col!r}): "
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
    parsed_dt = pd.to_datetime(df[dt_col], errors="coerce", format="mixed")

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
    print("E10 — VRN + Weight + ETC + Custom + Weight Group + Std Weight")
    print("=" * 60)

    load_env()
    config = load_config()
    entity_name, from_date, to_date = resolve_entity_and_dates()
    print(f"entity_name: {entity_name}")
    print(f"date range: {from_date} → {to_date}")

    print("-" * 60)
    print("Downloading / merging VRN…")
    vrn_path = run_vrn_download_merge(entity_name, from_date, to_date, config)
    print(f"Merged VRN: {vrn_path}")

    vrn_df = pd.read_csv(vrn_path, dtype=str, keep_default_na=False)
    print(f"Merged VRN rows: {len(vrn_df)}")
    print(f"Merged VRN columns: {list(vrn_df.columns)}")

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
    print("Joining VRN ↔ ETC on vehicle + date/hour…")
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
