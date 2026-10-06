"""
E6 — Local ETC folder + local VRN folder → TC Class → rates/Loss → DB.

1) Merge ETC Excel/CSV from ETC_INPUT_FOLDER (no download)
2) Merge VRN Excel/CSV from VRN_INPUT_FOLDER (no download); attach TC Class
3) Normalize Journey Type → rates → Loss; write enriched ETC
4) Optionally upsert audit_exception_metrics (exception id 6)

Run:
  1. Set ENTITY_NAME, ETC_INPUT_FOLDER, VRN_INPUT_FOLDER
  2. python E6_main.py
     or: python E6_main.py bassi <plaza_uuid>
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from e6_db_update import update_db_from_dataframe
from vehicle_number_utils import normalize_vehicle_number

BASE_DIR = Path(__file__).resolve().parent
E4_DIR = BASE_DIR.parent / "E4"
CONFIG_PATH = BASE_DIR / "e6_config.json"
ETC_DOWNLOAD_MERGE_PATH = E4_DIR / "etc-download-merge.py"
VRN_DOWNLOAD_MERGE_PATH = E4_DIR / "vrn-download-merge.py"
OUTPUT_DIR = BASE_DIR / "output"

# Import plaza rates from E4
if str(E4_DIR) not in sys.path:
    sys.path.insert(0, str(E4_DIR))
from plaza_rates import PLAZA_RATES, Plaza_Rates_Apr26_onwards  # noqa: E402

# --- Runtime inputs (edit these; not in config) ---
ENTITY_NAME = "mokha"
# Local ETC Excel/CSV folder for the period. Required — ETC is not downloaded.
ETC_INPUT_FOLDER = r"C:/Divyesh/Toll Analytics Dashboard/Exeption Programs/E6/etc_input"
# Local VRN Excel/CSV folder for the same period. Required — VRN is not downloaded.
VRN_INPUT_FOLDER = r"C:/Divyesh/Toll Analytics Dashboard/Exeption Programs/E6/vrn_input"
ETC_OUTPUT_FILE = OUTPUT_DIR / "etc_enriched.xlsx"
# plazas.plaza_identifier — required when UPDATE_DB is True
PLAZA_IDENTIFIER = "94ecdec1-550c-4b4c-a94d-1df3b5fb4ac6"
EXCEPTION_TYPE_ID = 6
# Last step: write monthly Loss totals into audit_exception_metrics
UPDATE_DB = False
DB_DRY_RUN = False


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _normalize_header_cell(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return " ".join(text.split())


def _normalize_header_key(value) -> str:
    return _normalize_header_cell(value).casefold()


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
        raise ValueError(
            "header_keywords is empty in e6_config.json — "
            "add ETC header column names to detect the header row."
        )

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
            f"ETC header row not detected (need >= {min_matches} keyword matches; "
            f"best score={best_score})."
        )
    return best_idx


def read_etc_raw(path: Path) -> pd.DataFrame:
    """Load first sheet with no header so we can locate it ourselves."""
    if not path.is_file():
        raise FileNotFoundError(f"ETC input file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    return pd.read_excel(path, sheet_name=0, header=None, dtype=str)


def dataframe_from_header(
    df_raw: pd.DataFrame,
    header_idx: int,
) -> tuple[list[str], pd.DataFrame]:
    headers = [_normalize_header_cell(v) for v in df_raw.iloc[header_idx].tolist()]
    while headers and headers[-1] == "":
        headers.pop()
    if not any(headers):
        raise ValueError("Detected ETC header row is empty")

    body = df_raw.iloc[header_idx + 1 :, : len(headers)].copy()
    body.columns = headers
    body = body.dropna(how="all").reset_index(drop=True)
    return headers, body


def load_etc(path: Path, config: dict) -> tuple[pd.DataFrame, int, list[str]]:
    """
    Detect header via keywords, return (dataframe, 0-based header_idx, header names).
    header_idx is kept for later steps that need the original sheet layout.
    """
    keywords = config.get("header_keywords") or []
    scan_rows = int(config.get("header_scan_rows") or 25)
    min_matches = int(config.get("min_header_matches") or 3)

    df_raw = read_etc_raw(path)
    if df_raw.empty:
        raise ValueError(f"ETC file is empty: {path}")

    header_idx = detect_header_row(
        df_raw,
        keywords,
        scan_rows=scan_rows,
        min_matches=min_matches,
    )
    headers, df = dataframe_from_header(df_raw, header_idx)
    print(
        f"ETC header at row {header_idx + 1} "
        f"(0-based index={header_idx}, {len(headers)} columns, {len(df)} data rows)"
    )
    return df, header_idx, headers


def resolve_vehicle_column(df: pd.DataFrame, columns_cfg: dict) -> str:
    preferred = str(columns_cfg.get("etc_vehicle") or "").strip()
    aliases = list(columns_cfg.get("etc_vehicle_aliases") or [])
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    for name in aliases:
        text = str(name).strip()
        if text and text not in candidates:
            candidates.append(text)

    col_lookup = {str(c).strip().casefold(): c for c in df.columns}
    for name in candidates:
        hit = col_lookup.get(name.casefold())
        if hit is not None:
            return hit

    raise KeyError(
        "Could not resolve ETC vehicle column from config. "
        f"Tried: {candidates}. Available: {list(df.columns)}"
    )


def resolve_column(df: pd.DataFrame, preferred: str, aliases: list[str]) -> str | None:
    candidates: list[str] = []
    pref = str(preferred or "").strip()
    if pref:
        candidates.append(pref)
    for name in aliases or []:
        text = str(name).strip()
        if text and text not in candidates:
            candidates.append(text)

    col_lookup = {_normalize_header_key(c): c for c in df.columns}
    for name in candidates:
        hit = col_lookup.get(_normalize_header_key(name))
        if hit is not None:
            return hit
    return None


def resolve_entity_name() -> str:
    if len(sys.argv) >= 2 and str(sys.argv[1]).strip():
        return str(sys.argv[1]).strip()
    name = str(ENTITY_NAME or "").strip()
    if name:
        return name
    name = input("Enter entity_name (submissions.entity_name): ").strip()
    if not name:
        raise RuntimeError("entity_name is required.")
    return name



def resolve_plaza_identifier() -> str:
    if len(sys.argv) >= 3 and str(sys.argv[2]).strip():
        return str(sys.argv[2]).strip()
    value = str(PLAZA_IDENTIFIER or "").strip()
    if value:
        return value
    value = input("Enter plaza_identifier (plazas.plaza_identifier): ").strip()
    if not value:
        raise RuntimeError("PLAZA_IDENTIFIER is required when UPDATE_DB is True.")
    return value


def build_etc_merge_config(e6_config: dict) -> dict:
    """ETC merge config: only the columns required for E6."""
    explicit = e6_config.get("etc_merge")
    if isinstance(explicit, dict) and explicit.get("merge_columns"):
        return explicit

    columns_cfg = e6_config.get("columns") or {}
    return {
        "header_keywords": list(e6_config.get("header_keywords") or []),
        "header_scan_rows": int(e6_config.get("header_scan_rows") or 25),
        "min_header_matches": int(e6_config.get("min_header_matches") or 3),
        "merge_columns": {
            "vehicle_reg_no": list(columns_cfg.get("etc_vehicle_aliases") or []),
            "read_datetime": list(columns_cfg.get("tag_read_datetime_aliases") or []),
            "journey_type": list(columns_cfg.get("journey_type_aliases") or []),
            "net_settlement_amt": list(columns_cfg.get("net_settlement_aliases") or []),
        },
    }


def load_etc_download_merge_module():
    path = ETC_DOWNLOAD_MERGE_PATH
    if not path.is_file():
        raise FileNotFoundError(f"ETC merge script not found: {path}")
    spec = importlib.util.spec_from_file_location("e4_etc_download_merge", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_etc_input_folder() -> Path:
    folder = Path(str(ETC_INPUT_FOLDER or "").strip())
    if not folder.is_absolute():
        folder = BASE_DIR / folder
    if not folder.is_dir():
        raise FileNotFoundError(
            f"ETC_INPUT_FOLDER not found or not a directory: {folder}\n"
            "Place ETC Excel/CSV files there (ETC is not downloaded)."
        )
    return folder


def resolve_vrn_input_folder() -> Path:
    folder = Path(str(VRN_INPUT_FOLDER or "").strip())
    if not folder.is_absolute():
        folder = BASE_DIR / folder
    if not folder.is_dir():
        raise FileNotFoundError(
            f"VRN_INPUT_FOLDER not found or not a directory: {folder}\n"
            "Place VRN Excel/CSV files there (VRN is not downloaded)."
        )
    return folder


def load_etc_from_folder(entity_name: str, config: dict) -> pd.DataFrame:
    """Merge local ETC Excel/CSV from ETC_INPUT_FOLDER (no DB download)."""
    folder = resolve_etc_input_folder()
    etc_cfg = build_etc_merge_config(config)
    if not etc_cfg.get("merge_columns"):
        raise RuntimeError("e6_config.json etc_merge.merge_columns is empty.")

    etc_mod = load_etc_download_merge_module()
    paths = etc_mod.list_local_etc_files(folder)
    if not paths:
        raise FileNotFoundError(f"No ETC Excel/CSV files found under: {folder}")

    print(f"Local ETC folder: {folder}")
    print(f"Found {len(paths)} ETC file(s)")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    merged_name = f"{etc_mod.safe_part(entity_name)}_local_merged_etc.csv"
    merged_path = etc_mod.merge_etc_files(paths, etc_cfg, OUTPUT_DIR / merged_name)
    df = pd.read_csv(merged_path, dtype=str, keep_default_na=False)
    print(f"ETC merge columns: {list((etc_cfg.get('merge_columns') or {}).keys())}")
    print(f"Merged ETC rows: {len(df)} | columns: {list(df.columns)}")
    return df


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
    etc_df: pd.DataFrame,
    vehicle_col: str,
    vrn_lookup: dict[str, str],
    columns_cfg: dict,
) -> pd.DataFrame:
    out_col = str(columns_cfg.get("tc_class_output") or "TC Class").strip() or "TC Class"
    vehs = etc_df[vehicle_col].map(normalize_vehicle_number)
    tc_values = [vrn_lookup.get(v, "") for v in vehs.tolist()]

    result = etc_df.copy()
    result[out_col] = tc_values
    matched = sum(1 for v in tc_values if v)
    print(
        f"TC Class attached via VRN on {vehicle_col!r} → {out_col!r}: "
        f"{matched}/{len(result)} rows matched"
    )
    return result


def enrich_etc_with_vrn_tc_class(
    etc_df: pd.DataFrame,
    vehicle_col: str,
    columns_cfg: dict,
    entity_name: str,
    config: dict,
) -> pd.DataFrame:
    """Merge local VRN from VRN_INPUT_FOLDER and attach TC Class (no download)."""
    folder = resolve_vrn_input_folder()
    vrn_cfg = config.get("vrn_merge") or {}
    if not vrn_cfg.get("merge_columns"):
        raise RuntimeError("e6_config.json vrn_merge.merge_columns is empty.")

    vrn_mod = load_vrn_download_merge_module()
    paths = vrn_mod.list_local_files(folder)
    if not paths:
        raise FileNotFoundError(f"No VRN Excel/CSV files found under: {folder}")

    print(f"Local VRN folder: {folder}")
    print(f"Found {len(paths)} VRN file(s)")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    merged_name = f"{vrn_mod.safe_part(entity_name)}_local_merged_vrn.csv"
    date_order = ""
    try:
        date_order = vrn_mod.date_order_for(entity_name, vrn_mod.load_config())
        print(f"VRN date order for {entity_name}: {date_order}")
    except RuntimeError as exc:
        print(f"{exc} Date & Time values are kept as read.")

    vrn_path = vrn_mod.merge_vrn_files(
        paths,
        vrn_cfg,
        OUTPUT_DIR / merged_name,
        date_order,
    )
    print(f"VRN merge columns: {list((vrn_cfg.get('merge_columns') or {}).keys())}")
    print(f"Merged VRN: {vrn_path}")

    vrn_lookup = build_vrn_tc_class_lookup(Path(vrn_path))
    return attach_tc_class_from_vrn(etc_df, vehicle_col, vrn_lookup, columns_cfg)


def normalize_value_key(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    # Treat /, \, _, - like spaces so CAR\JEEP / car/jeep match car jeep.
    text = re.sub(r"[\s_\-/\\]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in {"", "nan", "none", "nat"}:
        return ""
    return text


def build_name_to_category_lookup(category_map: dict) -> dict[str, str]:
    """
    category_map shape: { "single": ["single", "annualpass"], "return": [...], ... }
    → normalized alias → category key (plaza_rates key).
    """
    lookup: dict[str, str] = {}
    for category, names in (category_map or {}).items():
        cat = str(category).strip().lower()
        if not cat:
            continue
        # category key itself is always accepted
        lookup[normalize_value_key(cat)] = cat
        for name in names or []:
            key = normalize_value_key(name)
            if key:
                lookup[key] = cat
    return lookup


def build_tc_class_index_lookup(raw_map: dict) -> dict[str, int]:
    lookup: dict[str, int] = {}
    list_style = any(isinstance(v, list) for v in (raw_map or {}).values())
    if list_style:
        for idx_raw, names in raw_map.items():
            idx = int(idx_raw)
            for name in names or []:
                key = normalize_value_key(name)
                if key:
                    lookup[key] = idx
    else:
        for name, idx in (raw_map or {}).items():
            key = normalize_value_key(name)
            if key:
                lookup[key] = int(idx)
    if not lookup:
        raise RuntimeError("tc_class_index_map is empty in e6_config.json")
    return lookup


def build_tc_class_skip_set(names: list) -> set[str]:
    return {normalize_value_key(n) for n in (names or []) if normalize_value_key(n)}


def parse_rate_cutover_date(config: dict) -> date:
    raw = str(config.get("rate_cutover_date") or "2026-05-01").strip()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid rate_cutover_date in config: {raw!r}") from exc


def select_plaza_rates_book(read_d: date, cutover: date) -> dict:
    if read_d < cutover:
        return PLAZA_RATES
    return Plaza_Rates_Apr26_onwards


def lookup_journey_rate(
    entity_name: str,
    rates_book: dict,
    journey_key: str,
    class_index: int,
) -> float:
    key = str(entity_name or "").strip()
    plaza = rates_book.get(key) or rates_book.get(key.lower())
    if plaza is None:
        book_name = (
            "PLAZA_RATES"
            if rates_book is PLAZA_RATES
            else "Plaza_Rates_Apr26_onwards"
        )
        raise RuntimeError(f"Entity {entity_name!r} not found in plaza rates ({book_name})")

    journey_rates = plaza.get(journey_key) if isinstance(plaza, dict) else None
    if not isinstance(journey_rates, dict):
        raise RuntimeError(
            f"No {journey_key!r} rates for entity {entity_name!r}"
        )
    if class_index not in journey_rates:
        raise RuntimeError(
            f"No {journey_key!r} rate for class index {class_index} "
            f"on entity {entity_name!r}"
        )
    return float(journey_rates[class_index])


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


def normalize_journey_types(etc_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    columns_cfg = config.get("columns") or {}
    journey_col = resolve_column(
        etc_df,
        str(columns_cfg.get("journey_type") or ""),
        list(columns_cfg.get("journey_type_aliases") or []),
    )
    if not journey_col:
        raise RuntimeError(
            "Journey Type column not found. "
            f"Available: {list(etc_df.columns)}"
        )

    out_col = (
        str(columns_cfg.get("journey_type_normalized_output") or journey_col).strip()
        or journey_col
    )
    journey_lookup = build_name_to_category_lookup(config.get("journey_type_map") or {})
    if not journey_lookup:
        raise RuntimeError("journey_type_map is empty in e6_config.json")
    exclude_set = build_tc_class_skip_set(config.get("journey_type_exclude") or [])

    normalized: list[str] = []
    unknown: set[str] = set()
    excluded = 0
    for raw in etc_df[journey_col].tolist():
        key = normalize_value_key(raw)
        if not key:
            normalized.append("")
            continue
        if key in exclude_set:
            normalized.append("")
            excluded += 1
            continue
        cat = journey_lookup.get(key)
        if cat is None:
            unknown.add(str(raw).strip())
            normalized.append("")
            continue
        normalized.append(cat)

    if unknown:
        raise RuntimeError(
            "Unknown Journey Type value(s) not in journey_type_map — stopping: "
            + ", ".join(sorted(repr(v) for v in unknown))
        )

    result = etc_df.copy()
    result[out_col] = normalized
    counts = (
        pd.Series(normalized).replace("", pd.NA).dropna().value_counts().to_dict()
    )
    print(
        f"Journey Type normalized on {journey_col!r} → {out_col!r}: {counts}"
        + (f", excluded={excluded}" if excluded else "")
    )
    return result


def apply_rates_and_loss(
    etc_df: pd.DataFrame,
    config: dict,
    entity_name: str,
) -> pd.DataFrame:
    columns_cfg = config.get("columns") or {}

    journey_col = resolve_column(
        etc_df,
        str(columns_cfg.get("journey_type_normalized_output") or "Journey Type"),
        list(columns_cfg.get("journey_type_aliases") or [])
        + [str(columns_cfg.get("journey_type") or "Journey Type")],
    )
    tc_col = resolve_column(
        etc_df,
        str(columns_cfg.get("tc_class_output") or columns_cfg.get("tc_class") or ""),
        list(columns_cfg.get("tc_class_aliases") or []),
    )
    settle_col = resolve_column(
        etc_df,
        str(columns_cfg.get("net_settlement") or ""),
        list(columns_cfg.get("net_settlement_aliases") or []),
    )
    tag_col = resolve_column(
        etc_df,
        str(columns_cfg.get("tag_read_datetime") or ""),
        list(columns_cfg.get("tag_read_datetime_aliases") or []),
    )

    missing = []
    if not journey_col:
        missing.append("Journey Type")
    if not tc_col:
        missing.append("TC Class")
    if not settle_col:
        missing.append("Net Settlement Amt")
    if not tag_col:
        missing.append("Tag Read Date Time")
    if missing:
        raise RuntimeError(
            "Cannot compute Applicable Rate / Loss — missing columns: "
            + ", ".join(missing)
        )

    rate_col = (
        str(columns_cfg.get("applicable_rate_output") or "Applicable Rate").strip()
        or "Applicable Rate"
    )
    loss_col = str(columns_cfg.get("loss_output") or "Loss").strip() or "Loss"

    cutover = parse_rate_cutover_date(config)
    tc_lookup = build_tc_class_index_lookup(config.get("tc_class_index_map") or {})
    skip_set = build_tc_class_skip_set(config.get("tc_class_skip_list") or [])
    journey_lookup = build_name_to_category_lookup(config.get("journey_type_map") or {})

    tag_parsed = pd.to_datetime(etc_df[tag_col], errors="coerce")
    settlements = [_to_float_or_none(v) for v in etc_df[settle_col].tolist()]

    rates: list[float | None] = []
    losses: list[float | None] = []
    rated = 0
    skipped = 0

    for journey_raw, tc_raw, settle, tag_ts in zip(
        etc_df[journey_col].tolist(),
        etc_df[tc_col].tolist(),
        settlements,
        tag_parsed.tolist(),
    ):
        journey_key = normalize_value_key(journey_raw)
        # Already normalized to single/return/local, but accept aliases too
        journey_cat = journey_lookup.get(journey_key) if journey_key else None
        if journey_key and journey_cat is None and journey_key in {"single", "return", "local"}:
            journey_cat = journey_key

        tc_key = normalize_value_key(tc_raw)
        if tc_key and tc_key in skip_set:
            rates.append(None)
            losses.append(None)
            skipped += 1
            continue

        if not journey_cat or not tc_key or tag_ts is None or pd.isna(tag_ts):
            rates.append(None)
            losses.append(None)
            continue

        if tc_key not in tc_lookup:
            raise RuntimeError(
                f"Unknown TC Class {tc_raw!r} (normalized {tc_key!r}) — "
                "not present in tc_class_index_map. Stopping."
            )
        class_index = tc_lookup[tc_key]
        read_d = pd.Timestamp(tag_ts).date()
        rates_book = select_plaza_rates_book(read_d, cutover)
        rate = lookup_journey_rate(entity_name, rates_book, journey_cat, class_index)
        rates.append(rate)
        if settle is None:
            losses.append(None)
        else:
            losses.append(rate - float(settle))
        rated += 1

    result = etc_df.copy()
    result[rate_col] = rates
    result[loss_col] = losses
    nonzero_loss = sum(
        1 for v in losses if v is not None and abs(float(v)) > 1e-9
    )
    print(
        f"Applicable Rate / Loss for entity {entity_name!r} "
        f"(cutover {cutover.isoformat()}): "
        f"{rated}/{len(result)} rated"
        + (f", skipped TC={skipped}" if skipped else "")
        + f", Loss ≠ 0: {nonzero_loss}"
    )
    return result


def save_etc(df: pd.DataFrame, path: Path) -> Path:
    path = Path(path)
    if not path.is_absolute():
        path = BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)
    return path


def main() -> int:
    print("=" * 60)
    print("E6 — local ETC + local VRN + rates/Loss")
    print(f"ETC_INPUT_FOLDER = {ETC_INPUT_FOLDER!r}")
    print(f"VRN_INPUT_FOLDER = {VRN_INPUT_FOLDER!r}")
    print("=" * 60)

    config = load_config()
    columns_cfg = config.get("columns") or {}
    entity_name = resolve_entity_name()
    print(f"entity_name: {entity_name}")

    print("-" * 60)
    print("Loading / merging local ETC…")
    etc_df = load_etc_from_folder(entity_name, config)
    vehicle_col = resolve_vehicle_column(etc_df, columns_cfg)
    print(f"Vehicle column: {vehicle_col}")

    print("-" * 60)
    print("Loading / merging local VRN and attaching TC Class…")
    enriched = enrich_etc_with_vrn_tc_class(
        etc_df,
        vehicle_col,
        columns_cfg,
        entity_name,
        config,
    )

    print("-" * 60)
    enriched = normalize_journey_types(enriched, config)
    enriched = apply_rates_and_loss(enriched, config, entity_name)

    out_path = save_etc(enriched, Path(ETC_OUTPUT_FILE))
    print(f"Wrote enriched ETC: {out_path}")
    print(f"Rows: {len(enriched)} | Columns: {list(enriched.columns)}")

    if not UPDATE_DB:
        print("UPDATE_DB=False — audit_exception_metrics not updated.")
        return 0

    plaza_identifier = resolve_plaza_identifier()
    print("-" * 60)
    print("Updating audit_exception_metrics (exception_type_id=6)…")
    columns_cfg = config.get("columns") or {}
    update_db_from_dataframe(
        enriched,
        plaza_identifier,
        exception_type_id=int(EXCEPTION_TYPE_ID),
        dry_run=bool(DB_DRY_RUN),
        tag_date_aliases=(
            [str(columns_cfg.get("tag_read_datetime") or "")]
            + list(columns_cfg.get("tag_read_datetime_aliases") or [])
        ),
        loss_aliases=[
            str(columns_cfg.get("loss_output") or "Loss"),
            "Loss",
        ],
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
