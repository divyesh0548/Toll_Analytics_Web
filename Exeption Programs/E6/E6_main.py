"""
E6 — Enrich ETC file with Parivahan permit scrape (step 1).

1) Load ETC Excel — detect header row via keywords in e6_config.json
2) Resolve vehicle column from e6_config.json
3) Scrape unique VRNs once via web_scrap_for_permit (Selenium Grid or local)
4) Join permit columns back onto every ETC row by vehicle reg no
5) Write enriched ETC (same columns + Permit Type / No / Validity)

e6_config.json is mappings + scrape settings only.
Runtime paths are set as variables below.

Run:
  1. Set ETC_INPUT_FILE (and optionally ETC_OUTPUT_FILE)
  2. Fill header_keywords in e6_config.json
  3. python E6_main.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from vehicle_number_utils import normalize_vehicle_number
from web_scrap_for_permit import PERMIT_FIELDS, scrape_vehicle_details_for_permit

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "e6_config.json"

# --- Runtime inputs (edit these; not in config) ---
USE_SELENIUM_GRID = True  # False = local Chrome
ETC_INPUT_FILE = BASE_DIR / "input" / "odhaki_etc_trimmed_Apr_26.xlsx"
# Enriched ETC with permit columns. Set equal to ETC_INPUT_FILE to overwrite.
ETC_OUTPUT_FILE = BASE_DIR / "output" / "etc_with_permit.xlsx"


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
    print("E6 — ETC + Permit scrape")
    print(f"USE_SELENIUM_GRID = {USE_SELENIUM_GRID}")
    print("=" * 60)

    config = load_config()
    columns_cfg = config.get("columns") or {}
    scrape_cfg = config.get("scrape") or {}

    etc_df, header_idx, headers = load_etc(Path(ETC_INPUT_FILE), config)
    vehicle_col = resolve_vehicle_column(etc_df, columns_cfg)
    print(f"ETC header_idx: {header_idx}")
    print(f"ETC headers: {headers}")
    print(f"ETC rows: {len(etc_df)}")
    print(f"Vehicle column: {vehicle_col}")

    unique_df = unique_vehicle_frame(etc_df, vehicle_col)
    print(f"Unique VRNs to scrape: {len(unique_df)}")

    if unique_df.empty:
        print("No vehicle numbers found — writing ETC unchanged with empty permit columns.")
        enriched = merge_permit_into_etc(etc_df, pd.DataFrame(), vehicle_col, columns_cfg)
    else:
        remote_url = scrape_cfg.get("selenium_remote_url") if USE_SELENIUM_GRID else None
        scraped = scrape_vehicle_details_for_permit(
            unique_df,
            remote_url=remote_url,
            use_selenium_grid=USE_SELENIUM_GRID,
            scrape_cfg=scrape_cfg,
            vehicle_column=vehicle_col,
        )
        enriched = merge_permit_into_etc(etc_df, scraped, vehicle_col, columns_cfg)

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
