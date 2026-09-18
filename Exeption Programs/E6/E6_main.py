"""
E6 — Enrich ETC with Parivahan permit scrape + VRN TC Class + rates/Loss.

1) Load ETC Excel — detect header row via keywords in e6_config.json
2) Resolve vehicle column from e6_config.json
3) Scrape unique VRNs once via web_scrap_for_permit (Selenium Grid or local)
4) Join permit columns back onto every ETC row by vehicle reg no
5) From Tag Read Date Time, take oldest→newest date range; download/merge VRN
   for entity_name (same module as E4); attach TC Class onto ETC
6) Normalize Journey Type → single / return / local; lookup plaza rate by
   journey + TC Class → Applicable Rate; Loss = Applicable Rate − Net Settlement Amt
7) Write enriched ETC

e6_config.json holds column aliases, journey/TC maps, and scrape settings.
Runtime paths / entity are set as variables below.

Run:
  1. Set ETC_INPUT_FILE, ENTITY_NAME (and optionally ETC_OUTPUT_FILE)
  2. Fill header_keywords / journey_type_map in e6_config.json
  3. For development: set SKIP_PERMIT_SCRAPE_FOR_DEV = True to reuse
     existing ETC_OUTPUT_FILE and skip Parivahan scraping
  4. python E6_main.py
     or: python E6_main.py odhaki_paipkhar
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from vehicle_number_utils import normalize_vehicle_number
from web_scrap_for_permit import PERMIT_FIELDS, scrape_vehicle_details_for_permit

BASE_DIR = Path(__file__).resolve().parent
E4_DIR = BASE_DIR.parent / "E4"
CONFIG_PATH = BASE_DIR / "e6_config.json"
VRN_DOWNLOAD_MERGE_PATH = E4_DIR / "vrn-download-merge.py"

# Import plaza rates from E4
if str(E4_DIR) not in sys.path:
    sys.path.insert(0, str(E4_DIR))
from plaza_rates import PLAZA_RATES, Plaza_Rates_Apr26_onwards  # noqa: E402

# --- Runtime inputs (edit these; not in config) ---
USE_SELENIUM_GRID = True  # False = local Chrome
ETC_INPUT_FILE = BASE_DIR / "input" / "odhaki_etc_trimmed_Apr_26.xlsx"
# Enriched ETC with permit columns. Set equal to ETC_INPUT_FILE to overwrite.
ETC_OUTPUT_FILE = BASE_DIR / "output" / "etc_with_permit.xlsx"
# submissions.entity_name — used for VRN download/merge and plaza rates
ENTITY_NAME = "odhaki_paipkhar"
# DEV ONLY: skip Parivahan permit scrape; start from existing ETC_OUTPUT_FILE
# (already has permit columns). Set False for the full production pipeline.
SKIP_PERMIT_SCRAPE_FOR_DEV = True


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
        raise RuntimeError("entity_name is required for VRN download.")
    return name


def tag_read_date_range(etc_df: pd.DataFrame, columns_cfg: dict) -> tuple[date, date]:
    """Oldest and newest calendar dates from Tag Read Date Time (YYYY-MM-DD HH:MM:SS)."""
    col = resolve_column(
        etc_df,
        str(columns_cfg.get("tag_read_datetime") or ""),
        list(columns_cfg.get("tag_read_datetime_aliases") or []),
    )
    if not col:
        raise RuntimeError(
            "Tag Read Date Time column not found. "
            f"Available: {list(etc_df.columns)}"
        )

    parsed = pd.to_datetime(etc_df[col], errors="coerce")
    if parsed.isna().all():
        raise RuntimeError(f"No valid datetimes in column {col!r}")

    earliest = parsed.min()
    latest = parsed.max()
    start_d = earliest.date() if hasattr(earliest, "date") else pd.Timestamp(earliest).date()
    end_d = latest.date() if hasattr(latest, "date") else pd.Timestamp(latest).date()
    if end_d < start_d:
        raise RuntimeError(
            f"Invalid Tag Read Date Time range: {start_d} is after {end_d}"
        )
    print(
        f"Tag Read Date Time range from {col!r}: "
        f"{start_d.isoformat()} → {end_d.isoformat()}"
    )
    return start_d, end_d


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
) -> pd.DataFrame:
    start_d, end_d = tag_read_date_range(etc_df, columns_cfg)
    print(f"Starting VRN download/merge for entity_name={entity_name!r}")

    vrn_mod = load_vrn_download_merge_module()
    vrn_path = vrn_mod.run_vrn_download_merge(
        entity_name,
        start_d.isoformat(),
        end_d.isoformat(),
    )
    if vrn_path is None:
        raise RuntimeError("VRN download finished without a merged file path.")
    print(f"VRN merge complete: {vrn_path}")

    vrn_lookup = build_vrn_tc_class_lookup(Path(vrn_path))
    return attach_tc_class_from_vrn(etc_df, vehicle_col, vrn_lookup, columns_cfg)


def normalize_value_key(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[\s_\-]+", " ", text)
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

    normalized: list[str] = []
    unknown: set[str] = set()
    for raw in etc_df[journey_col].tolist():
        key = normalize_value_key(raw)
        if not key:
            normalized.append("")
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
    print(f"Journey Type normalized on {journey_col!r} → {out_col!r}: {counts}")
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


def unique_vehicle_frame(etc_df: pd.DataFrame, vehicle_col: str) -> pd.DataFrame:
    series = (
        etc_df[vehicle_col]
        .map(normalize_vehicle_number)
        .replace("", pd.NA)
        .dropna()
        .drop_duplicates()
        .reset_index(drop=True)
    )
    return pd.DataFrame({vehicle_col: series})


def merge_permit_into_etc(
    etc_df: pd.DataFrame,
    scraped_df: pd.DataFrame,
    vehicle_col: str,
    columns_cfg: dict,
) -> pd.DataFrame:
    """
    Left-join scrape results onto full ETC by normalized VRN.
    Duplicate ETC rows for the same VRN all receive the same permit fields.
    """
    permit_type = columns_cfg.get("permit_type") or PERMIT_FIELDS[0]
    permit_no = columns_cfg.get("permit_no") or PERMIT_FIELDS[1]
    permit_validity = columns_cfg.get("permit_validity") or PERMIT_FIELDS[2]
    permit_cols = [permit_type, permit_no, permit_validity]

    out = etc_df.copy()
    out["_join_key"] = out[vehicle_col].map(normalize_vehicle_number)

    if scraped_df is None or scraped_df.empty:
        for col in permit_cols:
            if col not in out.columns:
                out[col] = ""
        return out.drop(columns=["_join_key"])

    right = scraped_df.copy()
    # Scraper may have renamed/normalized the vehicle column in place.
    scrape_veh = vehicle_col if vehicle_col in right.columns else None
    if scrape_veh is None:
        for col in right.columns:
            key = str(col).casefold()
            if "veh" in key and "reg" in key:
                scrape_veh = col
                break
    if scrape_veh is None:
        raise KeyError(
            f"Scraped frame missing vehicle column. Available: {list(right.columns)}"
        )

    # Map scraper's fixed field names onto configured output column names.
    rename_map = {}
    for src, dst in zip(PERMIT_FIELDS, permit_cols):
        if src in right.columns:
            rename_map[src] = dst
        elif dst in right.columns:
            rename_map[dst] = dst
    right = right.rename(columns=rename_map)
    for col in permit_cols:
        if col not in right.columns:
            right[col] = ""

    right["_join_key"] = right[scrape_veh].map(normalize_vehicle_number)
    right = (
        right[right["_join_key"].ne("")]
        .drop_duplicates(subset=["_join_key"], keep="first")
        [["_join_key", *permit_cols]]
    )

    # Drop any pre-existing permit columns so merge replaces cleanly.
    drop_existing = [c for c in permit_cols if c in out.columns]
    if drop_existing:
        out = out.drop(columns=drop_existing)

    merged = out.merge(right, on="_join_key", how="left").drop(columns=["_join_key"])
    for col in permit_cols:
        merged[col] = merged[col].fillna("")
    return merged


def save_etc(df: pd.DataFrame, path: Path) -> Path:
    path = Path(path)
    if not path.is_absolute():
        path = BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)
    return path


def main() -> int:
    print("=" * 60)
    print("E6 — ETC + Permit scrape + VRN TC Class + rates/Loss")
    print(f"USE_SELENIUM_GRID = {USE_SELENIUM_GRID}")
    print(f"SKIP_PERMIT_SCRAPE_FOR_DEV = {SKIP_PERMIT_SCRAPE_FOR_DEV}")
    print("=" * 60)

    config = load_config()
    columns_cfg = config.get("columns") or {}
    scrape_cfg = config.get("scrape") or {}
    entity_name = resolve_entity_name()
    print(f"entity_name: {entity_name}")

    if SKIP_PERMIT_SCRAPE_FOR_DEV:
        # Development shortcut: reuse already-scraped permit output.
        start_path = Path(ETC_OUTPUT_FILE)
        if not start_path.is_file():
            raise FileNotFoundError(
                "SKIP_PERMIT_SCRAPE_FOR_DEV=True but ETC_OUTPUT_FILE not found: "
                f"{start_path}"
            )
        print(
            "DEV: skipping permit scrape — loading existing file:\n"
            f"  {start_path}"
        )
        enriched, header_idx, headers = load_etc(start_path, config)
        vehicle_col = resolve_vehicle_column(enriched, columns_cfg)
        print(f"ETC header_idx: {header_idx}")
        print(f"ETC headers: {headers}")
        print(f"ETC rows: {len(enriched)}")
        print(f"Vehicle column: {vehicle_col}")
    else:
        etc_df, header_idx, headers = load_etc(Path(ETC_INPUT_FILE), config)
        vehicle_col = resolve_vehicle_column(etc_df, columns_cfg)
        print(f"ETC header_idx: {header_idx}")
        print(f"ETC headers: {headers}")
        print(f"ETC rows: {len(etc_df)}")
        print(f"Vehicle column: {vehicle_col}")

        unique_df = unique_vehicle_frame(etc_df, vehicle_col)
        print(f"Unique VRNs to scrape: {len(unique_df)}")

        if unique_df.empty:
            print(
                "No vehicle numbers found — writing ETC unchanged "
                "with empty permit columns."
            )
            enriched = merge_permit_into_etc(
                etc_df, pd.DataFrame(), vehicle_col, columns_cfg
            )
        else:
            remote_url = (
                scrape_cfg.get("selenium_remote_url") if USE_SELENIUM_GRID else None
            )
            scraped = scrape_vehicle_details_for_permit(
                unique_df,
                remote_url=remote_url,
                use_selenium_grid=USE_SELENIUM_GRID,
                scrape_cfg=scrape_cfg,
                vehicle_column=vehicle_col,
            )
            enriched = merge_permit_into_etc(
                etc_df, scraped, vehicle_col, columns_cfg
            )
        # Persist permit stage so DEV skip can reuse it later.
        save_etc(enriched, Path(ETC_OUTPUT_FILE))

    print("-" * 60)
    enriched = enrich_etc_with_vrn_tc_class(
        enriched, vehicle_col, columns_cfg, entity_name
    )

    print("-" * 60)
    enriched = normalize_journey_types(enriched, config)
    enriched = apply_rates_and_loss(enriched, config, entity_name)

    out_path = save_etc(enriched, Path(ETC_OUTPUT_FILE))
    print(f"Wrote enriched ETC: {out_path}")
    print(f"Rows: {len(enriched)} | Columns: {list(enriched.columns)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
