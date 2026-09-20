"""
E5 — Incorrect FASTag class check (single click).

1) Read VRNs + correct class from plaza combined Excel
2) Scrape IHMCL (Selenium Grid or local Chrome)
3) Keep only rows where scraped Mapper Vehicle Class matches input class
   via aliases in e5_config.json
4) Aggregate matched rows by month and upsert audit_exception_metrics (E05)

Run full pipeline:
  python E5_main.py

Run DB update only:
  Edit MATCHED_OUTPUT_FILE / PLAZA_IDENTIFIER in e5_db_update.py
  Set DB_UPDATE_ONLY = True
  python e5_db_update.py
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd

from e5_db_update import update_db_from_dataframe

# ---------------------------------------------------------------------------
# Single-click toggles / paths
# ---------------------------------------------------------------------------
USE_SELENIUM_GRID = False  # False = local Chrome via IHMCL_bot.py
SKIP_DB_UPDATE = False  # True = scrape/compare only, no DB write

BASE_DIR = Path(__file__).resolve().parent
INPUT_EXCEL = BASE_DIR / "odhaki_paipkhar_combined_2026-06-01_to_2026-07-31.xlsx"
CONFIG_JSON = BASE_DIR / "e5_config.json"
OUTPUT_DIR = BASE_DIR / "output"

# ---------------------------------------------------------------------------


def load_config(path: Path = CONFIG_JSON) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def normalize_key(value) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    if text.lower() in {"nan", "none"}:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text)


def normalize_class(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return re.sub(r"\s+", " ", text)


def classes_match(input_class: str, scraped_class: str, class_aliases: dict) -> bool:
    """
    === CLASS ALIAS MAPPING IS APPLIED HERE ===

    Edit `class_aliases` in e5_config.json:
      - keys   = standard classes from the INPUT file (input_class column)
      - values = list of allowed labels from the SCRAPE output (scraped_class column)

    A row matches when scraped_class is listed under that input_class key
    (case-insensitive, whitespace-normalized). Exact string match is also accepted.
    """
    left = normalize_class(input_class)
    right = normalize_class(scraped_class)
    if not left or not right:
        return False
    if left.casefold() == right.casefold():
        return True

    # Resolve alias list for this input standard class (exact key, then casefold)
    allowed = class_aliases.get(left)
    if allowed is None:
        for key, values in class_aliases.items():
            if normalize_class(key).casefold() == left.casefold():
                allowed = values
                break
    if not allowed:
        return False

    allowed_norm = {normalize_class(v).casefold() for v in allowed}
    return right.casefold() in allowed_norm


def load_input_dataframe(input_path: Path, columns: dict) -> pd.DataFrame:
    if not input_path.exists():
        raise FileNotFoundError(f"Input Excel not found: {input_path}")
    df = pd.read_excel(input_path)
    vehicle_col = columns["input_vehicle"]
    class_col = columns["input_class"]
    for col in (vehicle_col, class_col):
        if col not in df.columns:
            raise KeyError(
                f"Column '{col}' missing in {input_path.name}. "
                f"Available: {list(df.columns)}"
            )
    df = df.copy()
    df[vehicle_col] = df[vehicle_col].astype(str).str.strip()
    df = df[df[vehicle_col].ne("") & ~df[vehicle_col].str.lower().isin(["nan", "none"])]
    return df.reset_index(drop=True)


def unique_vehicle_frame(input_df: pd.DataFrame, vehicle_col: str) -> pd.DataFrame:
    vehicles = (
        input_df[[vehicle_col]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    return vehicles


def scrape_local(vehicle_df: pd.DataFrame, vehicle_col: str, scrape_cfg: dict) -> pd.DataFrame:
    from IHMCL_bot import scrape_ihmcl_for_dataframe

    print(f"Local scrape: {len(vehicle_df)} unique VRN(s)")
    return scrape_ihmcl_for_dataframe(
        vehicle_df,
        vehicle_column_names=[vehicle_col, "Veh Reg No", "Veh Reg No."],
        mobile_number=scrape_cfg.get("mobile_number", "9999999999"),
        plaza_name=scrape_cfg.get("plaza_name", "Phulwaria Toll Plaza"),
    )


def scrape_via_grid(vehicle_df: pd.DataFrame, vehicle_col: str, scrape_cfg: dict) -> pd.DataFrame:
    from IHMCL_bot_selenium import scrape_ihmcl_for_dataframe
    from selenium_grid_manager import (
        split_dataframe,
        start_managed_nodes,
        stop_managed_nodes,
        wait_for_grid_ready,
        assert_grid_ready,
    )

    remote_url = scrape_cfg.get("selenium_remote_url", "http://localhost:4444/wd/hub")
    max_nodes = int(scrape_cfg.get("max_nodes", 3))
    headless = bool(scrape_cfg.get("headless", False))
    auto_manage = bool(scrape_cfg.get("auto_manage_nodes", True))
    mobile = scrape_cfg.get("mobile_number", "9999999999")
    plaza = scrape_cfg.get("plaza_name", "Phulwaria Toll Plaza")

    chunks = split_dataframe(vehicle_df, max_nodes)
    if not chunks:
        return pd.DataFrame()

    print(f"Grid scrape: {len(vehicle_df)} VRN(s) in {len(chunks)} chunk(s) → {remote_url}")

    managed_nodes: list[str] = []
    results: list[pd.DataFrame] = []
    failures: list[tuple[int, str]] = []

    try:
        if auto_manage:
            managed_nodes = start_managed_nodes(len(chunks))
            wait_for_grid_ready(remote_url)
        else:
            assert_grid_ready(remote_url)

        def _run_chunk(chunk_df: pd.DataFrame, chunk_id: int) -> pd.DataFrame:
            print(f"[Chunk {chunk_id}] {len(chunk_df)} vehicle(s)")
            out = scrape_ihmcl_for_dataframe(
                chunk_df,
                vehicle_column_names=[vehicle_col, "Veh Reg No", "Veh Reg No."],
                mobile_number=mobile,
                plaza_name=plaza,
                remote_url=remote_url,
                headless=headless,
            )
            if out is None:
                return pd.DataFrame()
            out = out.copy()
            out["source_chunk"] = chunk_id
            return out

        with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
            futures = {
                executor.submit(_run_chunk, chunk, idx): idx
                for idx, chunk in enumerate(chunks, start=1)
            }
            for future in as_completed(futures):
                chunk_id = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    failures.append((chunk_id, str(exc)))
                    print(f"[Chunk {chunk_id}] Failed: {exc}")
    finally:
        if managed_nodes:
            stop_managed_nodes(managed_nodes)

    if failures:
        print("Some grid chunks failed:")
        for chunk_id, err in failures:
            print(f"  - Chunk {chunk_id}: {err}")

    frames = [f for f in results if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)


def filter_matching_rows(
    input_df: pd.DataFrame,
    scraped_df: pd.DataFrame,
    columns: dict,
    class_aliases: dict,
) -> pd.DataFrame:
    """Join scrape onto input and keep rows where classes match via aliases."""
    in_veh = columns["input_vehicle"]
    in_cls = columns["input_class"]
    sc_veh = columns["scraped_vehicle"]
    sc_cls = columns["scraped_class"]

    if scraped_df is None or scraped_df.empty:
        print("No scraped rows — nothing to compare.")
        return input_df.iloc[0:0].copy()

    for col in (sc_veh, sc_cls):
        if col not in scraped_df.columns:
            raise KeyError(
                f"Scraped column '{col}' missing. Available: {list(scraped_df.columns)}"
            )

    left = input_df.copy()
    right = scraped_df.copy()
    left["_join_key"] = left[in_veh].map(normalize_key)
    right["_join_key"] = right[sc_veh].map(normalize_key)
    right = right[right["_join_key"].ne("")]

    scrape_keep = right[["_join_key", sc_veh, sc_cls]].rename(
        columns={
            sc_veh: "ihmcl_vehicle_number",
            sc_cls: "ihmcl_mapper_vehicle_class",
        }
    )
    # One input row × many scrape rows is OK — keep if ANY scrape class matches.
    merged = left.merge(scrape_keep, on="_join_key", how="inner")

    # --- CLASS ALIAS MAPPING APPLIED HERE (see classes_match / e5_config.json) ---
    merged["_class_match"] = merged.apply(
        lambda row: classes_match(
            row[in_cls],
            row["ihmcl_mapper_vehicle_class"],
            class_aliases,
        ),
        axis=1,
    )

    joined_vrns = merged["_join_key"].nunique()
    matched_keys = set(merged.loc[merged["_class_match"], "_join_key"])
    print(
        f"Class compare: {len(merged)} join row(s) across {joined_vrns} VRN(s); "
        f"{len(matched_keys)} VRN(s) matched aliases"
    )

    # Keep ALL input transaction rows for matched VRNs (needed for monthly DB totals).
    scrape_one = (
        merged.loc[merged["_class_match"]]
        .drop_duplicates(subset=["_join_key"], keep="first")[
            ["_join_key", "ihmcl_vehicle_number", "ihmcl_mapper_vehicle_class"]
        ]
    )
    matched = (
        left[left["_join_key"].isin(matched_keys)]
        .merge(scrape_one, on="_join_key", how="left")
        .drop(columns=["_join_key"])
        .reset_index(drop=True)
    )
    print(f"Matched transaction rows kept: {len(matched)}")
    return matched


def save_outputs(
    scraped_df: pd.DataFrame,
    matched_df: pd.DataFrame,
    output_dir: Path = OUTPUT_DIR,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scraped_path = output_dir / f"ihmcl_scrape_{stamp}.xlsx"
    matched_path = output_dir / f"e5_matched_{stamp}.xlsx"
    scraped_df.to_excel(scraped_path, index=False)
    matched_df.to_excel(matched_path, index=False)
    return scraped_path, matched_path


def main() -> int:
    print("=" * 60)
    print("E5 Incorrect FASTag class check")
    print(f"USE_SELENIUM_GRID = {USE_SELENIUM_GRID}")
    print("=" * 60)

    config = load_config(CONFIG_JSON)
    columns = config["columns"]
    class_aliases = config.get("class_aliases") or {}
    scrape_cfg = config.get("scrape") or {}

    if not class_aliases:
        print(
            "WARNING: class_aliases is empty in e5_config.json — "
            "fill it before relying on match results."
        )

    input_df = load_input_dataframe(INPUT_EXCEL, columns)
    vehicle_col = columns["input_vehicle"]
    print(f"Input rows: {len(input_df)}  file: {INPUT_EXCEL.name}")
    print(f"Using columns: vehicle='{vehicle_col}', class='{columns['input_class']}'")

    vehicle_df = unique_vehicle_frame(input_df, vehicle_col)
    print(f"Unique VRNs to scrape: {len(vehicle_df)}")

    if USE_SELENIUM_GRID:
        scraped_df = scrape_via_grid(vehicle_df, vehicle_col, scrape_cfg)
    else:
        scraped_df = scrape_local(vehicle_df, vehicle_col, scrape_cfg)

    if scraped_df is None:
        scraped_df = pd.DataFrame()
    print(f"Scraped rows: {len(scraped_df)}")

    matched_df = filter_matching_rows(input_df, scraped_df, columns, class_aliases)
    scraped_path, matched_path = save_outputs(scraped_df, matched_df)

    print("=" * 60)
    print(f"Scrape output : {scraped_path}")
    print(f"Matched rows  : {matched_path}  ({len(matched_df)} rows)")
    print("Edit class mapping in:", CONFIG_JSON)
    print("Mapping is applied in: classes_match() / filter_matching_rows()")

    if SKIP_DB_UPDATE:
        print("SKIP_DB_UPDATE=True — database not updated.")
    else:
        plaza_identifier = str(config.get("plaza_identifier") or "").strip()
        exception_type_id = int(config.get("exception_type_id") or 5)
        db_dry_run = bool(config.get("db_dry_run", False))
        if not plaza_identifier or plaza_identifier == "REPLACE_WITH_PLAZA_UUID":
            print(
                "WARNING: Set plaza_identifier in e5_config.json to write "
                "audit_exception_metrics. Skipping DB update."
            )
        else:
            print("-" * 60)
            print("Updating audit_exception_metrics…")
            update_db_from_dataframe(
                matched_df,
                plaza_identifier,
                exception_type_id=exception_type_id,
                dry_run=db_dry_run,
            )
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
