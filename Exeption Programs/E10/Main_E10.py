"""
E10 — VRN + checkpost Weight, then ETC download/merge, then VRN↔ETC join.

1) Download/merge VRN (vehicle_reg_no, tc_class, read_datetime from e10_config)
2) Drop rows whose TC Class is in the exclude list
3) Lookup weight from Checkpost DB by Unique Vehicle Number
4) Drop rows with null / empty / "0" / "N/A" Weight
5) Download/merge ETC (vehicle, datetime, Net Settlement, NPCI Class)
6) Join VRN↔ETC on normalized vehicle + date/hour key
   (e.g. "25-11-2025 08:00:17" → "25/11/2025|8 AM")
7) Add Custom weight-range band from Weight (ranges in e10_config.json)

DB credentials / source DBs: Website/backend/.env
  Source_DB_NAME + exceptions_Table_NAME → submissions (VRN + ETC)
  CHECKPOST_DB + CHECKPOST_TABLE → checkpost weights

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
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

BASE_DIR = Path(__file__).resolve().parent
E4_DIR = BASE_DIR.parent / "E4"
WEBSITE_ENV = BASE_DIR.parent.parent / "Website" / "backend" / ".env"
CONFIG_PATH = BASE_DIR / "e10_config.json"
VRN_DOWNLOAD_MERGE_PATH = E4_DIR / "vrn-download-merge.py"
ETC_DOWNLOAD_MERGE_PATH = E4_DIR / "etc-download-merge.py"
OUTPUT_DIR = BASE_DIR / "output"
ETC_DOWNLOAD_FOLDER = BASE_DIR / "etc_downloads"

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
    """Load Website/backend/.env and map names used by E4 download scripts."""
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

    # Checkpost aliases used by this script
    checkpost_db = os.getenv("CHECKPOST_DB", "").strip()
    if checkpost_db:
        os.environ["Checkpost_DB_NAME"] = checkpost_db
    checkpost_table = os.getenv("CHECKPOST_TABLE", "").strip()
    if checkpost_table:
        os.environ["Checkpost_Table_NAME"] = checkpost_table


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name} (in {WEBSITE_ENV})")
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
    print("E10 — VRN + Weight + ETC join + Custom weight band")
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
