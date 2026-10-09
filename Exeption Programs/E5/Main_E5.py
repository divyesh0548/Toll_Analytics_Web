"""
E5 — Invalid lookup query (IHMCL class check for 2-axle and above).

1) Read an invalid-table Excel/CSV
2) Split by Charged Vehicle Class into two sheets:
     - "Upto Lcv"          → VC20, VC4, VC5, VC9 only (no IHMCL scrape)
     - "2-axel and above"  → all other charged classes
3) Scrape unique VRNs from "2-axel and above" on IHMCL
4) Compare Correct Vehicle Class to IHMCL Mapper Vehicle Class by
   tc_class_index_map index (not free text)
5) Add column Matched = "yes" when indexes match (all rows kept)
6) On both sheets: map NPCI Class Desc and Correct Vehicle Class to rate
   indexes, Exception Value = Correct single rate - NPCI single rate
7) Optionally upsert audit_exception_metrics (exception id 5) for all months:
     - Upto Lcv: all rows, Impact by Reader Read Time month
     - 2-axel and above: Matched=yes only, same aggregation
     - Update existing month when new count OR amount is greater
8) Optional S3 upload of the workbook when UPLOAD_OUTPUT_TO_S3=True:
     - Before upload, drop 2-axel rows where Matched is empty or No
     - S3 file name includes exception code, plaza, month-year label

Different from E5_main.py:
  - Splits by Charged Vehicle Class first
  - Only scrapes the 2-axle+ sheet
  - Matches by class index (Correct vs IHMCL mapper)
  - Marks Matched instead of dropping non-matches (local Excel keeps all)

Run:
  1. Set INPUT_FILE, ENTITY_NAME, PLAZA_IDENTIFIER below
  2. python Main_E5.py

DB update only (existing workbook):
  python invalid_lookup_db_update.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BASE_DIR.parent))
from common.s3_output_upload import (  # noqa: E402
    month_label_from_periods,
    upload_exception_output,
)

CONFIG_JSON = BASE_DIR / "e5_config.json"
OUTPUT_DIR = BASE_DIR / "output"
MERGED_OUTPUT_HINT: Path = OUTPUT_DIR

# Import plaza rates (same module used by E5_main)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
from plaza_rates import PLAZA_RATES, Plaza_Rates_Apr26_onwards  # noqa: E402

# ---------------------------------------------------------------------------
# Runtime inputs (Website overrides via E5_* / EXCEPTION_USE_SELENIUM env)
# ---------------------------------------------------------------------------
INPUT_FILE = BASE_DIR / "invalid_table-aug-bassi.csv"  # change to your invalid Excel/CSV
ENTITY_NAME = "bassi"  # plaza_rates key for single-journey rates
PLAZA_IDENTIFIER = "94ecdec1-550c-4b4c-a94d-1df3b5fb4ac6"
EXCEPTION_TYPE_ID = 5
UPDATE_DB = True  # False = write Excel only, skip audit_exception_metrics
DB_DRY_RUN = False
# Upload filtered invalid_lookup workbook to S3 + audit_exception_output_files row.
UPLOAD_OUTPUT_TO_S3 = True
# True  = IHMCL_bot_selenium.py (Selenium Chrome)
# False = IHMCL_bot.py (legacy non-selenium path)
# Overridden by EXCEPTION_USE_SELENIUM / IHMCL_USE_SELENIUM in .env (global scrape flag).
USE_SELENIUM = True
# Used only when USE_SELENIUM=True. True = Selenium Grid; False = local Chrome.
USE_SELENIUM_GRID = True
SKIP_SCRAPE = False  # True = split sheets only, no IHMCL
# Optional pre-scraped IHMCL Excel/CSV (Vehicle Number + Mapper Vehicle Class).
IHMCL_INPUT_FILE = ""
MATCHED_YES = {"yes", "y", "true", "1"}


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def apply_website_env_overrides() -> None:
    """Apply E5_* / scrape env from Website job runner."""
    global INPUT_FILE, ENTITY_NAME, PLAZA_IDENTIFIER, UPDATE_DB, DB_DRY_RUN
    global UPLOAD_OUTPUT_TO_S3, USE_SELENIUM, USE_SELENIUM_GRID, SKIP_SCRAPE
    global IHMCL_INPUT_FILE, MERGED_OUTPUT_HINT

    if os.environ.get("E5_INPUT_FILE", "").strip():
        INPUT_FILE = Path(os.environ["E5_INPUT_FILE"].strip())
    if os.environ.get("E5_ENTITY_NAME", "").strip():
        ENTITY_NAME = os.environ["E5_ENTITY_NAME"].strip()
    if os.environ.get("E5_PLAZA_IDENTIFIER", "").strip():
        PLAZA_IDENTIFIER = os.environ["E5_PLAZA_IDENTIFIER"].strip()
    if "E5_METRICS_DB_UPDATE" in os.environ:
        UPDATE_DB = _env_flag("E5_METRICS_DB_UPDATE", UPDATE_DB)
    if "E5_UPLOAD_OUTPUT_TO_S3" in os.environ:
        UPLOAD_OUTPUT_TO_S3 = _env_flag("E5_UPLOAD_OUTPUT_TO_S3", UPLOAD_OUTPUT_TO_S3)
    if "E5_DB_DRY_RUN" in os.environ:
        DB_DRY_RUN = _env_flag("E5_DB_DRY_RUN", DB_DRY_RUN)
    if "E5_USE_SELENIUM_GRID" in os.environ:
        USE_SELENIUM_GRID = _env_flag("E5_USE_SELENIUM_GRID", USE_SELENIUM_GRID)
    if os.environ.get("E5_IHMCL_INPUT_FILE", "").strip():
        IHMCL_INPUT_FILE = os.environ["E5_IHMCL_INPUT_FILE"].strip()
        SKIP_SCRAPE = False  # use uploaded scrape file instead of live scrape
    if "E5_SKIP_SCRAPE" in os.environ and not IHMCL_INPUT_FILE:
        SKIP_SCRAPE = _env_flag("E5_SKIP_SCRAPE", SKIP_SCRAPE)
    if os.environ.get("E5_OUTPUT_DIR", "").strip():
        MERGED_OUTPUT_HINT = Path(os.environ["E5_OUTPUT_DIR"].strip())
    else:
        MERGED_OUTPUT_HINT = OUTPUT_DIR

    # Global scrape backend for all programs that need IHMCL.
    if "EXCEPTION_USE_SELENIUM" in os.environ:
        USE_SELENIUM = _env_flag("EXCEPTION_USE_SELENIUM", USE_SELENIUM)
    elif "IHMCL_USE_SELENIUM" in os.environ:
        USE_SELENIUM = _env_flag("IHMCL_USE_SELENIUM", USE_SELENIUM)

CHARGED_CLASS_COLUMN = "Charged Vehicle Class"
CORRECT_CLASS_COLUMN = "Correct Vehicle Class"
NPCI_CLASS_COLUMN = "NPCI Class Desc"
DATE_COLUMN_ALIASES = [
    "Reader Read Time",
    "Settlement Date",
    "Tag Read Date Time",
    "Date & Time",
]
# First match wins among these aliases for the VRN column on the input file.
VEHICLE_COLUMN_ALIASES = [
    "Licence Plate No",
    "Veh Reg No.",
    "Veh Reg No",
    "Vehicle Number",
    "Vehicle No",
    "Vehicle Reg No",
    "Reg No",
]

# Charged classes kept on sheet "Upto Lcv" (not scraped).
UPTO_LCV_CLASSES = ["VC20", "VC4", "VC5", "VC9"]

SHEET_UPTO_LCV = "Upto Lcv"
SHEET_TWO_AXLE = "2-axel and above"
# ---------------------------------------------------------------------------


def load_config(path: Path = CONFIG_JSON) -> dict:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_scrape_config(path: Path = CONFIG_JSON) -> dict:
    return load_config(path).get("scrape") or {}


def normalize_value_key(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[\s_\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in {"", "nan", "none", "nat"}:
        return ""
    return text


def build_tc_class_index_lookup(raw_map: dict) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for idx_raw, names in (raw_map or {}).items():
        idx = int(idx_raw)
        for name in names or []:
            key = normalize_value_key(name)
            if key:
                lookup[key] = idx
    if not lookup:
        raise RuntimeError("tc_class_index_map is empty in e5_config.json")
    return lookup


def parse_rate_cutover_date(config: dict) -> date:
    raw = str(config.get("rate_cutover_date") or "2026-05-01").strip()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid rate_cutover_date in config: {raw!r}") from exc


def select_plaza_rates_book(txn_d: date, cutover: date) -> dict:
    if txn_d < cutover:
        return PLAZA_RATES
    return Plaza_Rates_Apr26_onwards


def lookup_single_rate(entity_name: str, rates_book: dict, class_index: int) -> float:
    key = str(entity_name or "").strip()
    plaza = rates_book.get(key) or rates_book.get(key.lower())
    if plaza is None:
        raise RuntimeError(f"Entity {entity_name!r} not found in plaza rates")
    single = plaza.get("single") if isinstance(plaza, dict) else None
    if not isinstance(single, dict):
        raise RuntimeError(f"No 'single' rates for entity {entity_name!r}")
    if class_index not in single:
        raise RuntimeError(
            f"No single rate for class index {class_index} on entity {entity_name!r}"
        )
    return float(single[class_index])


def add_exception_values(
    df: pd.DataFrame,
    *,
    npci_col: str,
    correct_col: str,
    date_col: str | None,
    index_lookup: dict[str, int],
    entity_name: str,
    cutover: date,
    sheet_label: str,
    ) -> pd.DataFrame:
    """
    NPCI_class_index / Correct_class_index from tc_class_index_map.
    Exception Value = Correct single rate − NPCI single rate.
    """
    out = df.copy()
    unknown: set[str] = set()
    npci_indexes: list[int | None] = []
    correct_indexes: list[int | None] = []
    values: list[float | None] = []

    if date_col and date_col in out.columns:
        dates = pd.to_datetime(out[date_col], errors="coerce")
    else:
        dates = pd.Series([pd.NaT] * len(out))

    for npci_raw, correct_raw, ts in zip(
        out[npci_col].tolist(),
        out[correct_col].tolist(),
        dates.tolist(),
    ):
        npci_key = normalize_value_key(npci_raw)
        correct_key = normalize_value_key(correct_raw)
        npci_idx = index_lookup.get(npci_key) if npci_key else None
        correct_idx = index_lookup.get(correct_key) if correct_key else None

        if npci_key and npci_idx is None:
            unknown.add(str(npci_raw).strip())
        if correct_key and correct_idx is None:
            unknown.add(str(correct_raw).strip())

        npci_indexes.append(npci_idx)
        correct_indexes.append(correct_idx)

        if npci_idx is None or correct_idx is None:
            values.append(None)
            continue
        txn_d = (
            pd.Timestamp(ts).date()
            if ts is not None and not pd.isna(ts)
            else cutover
        )
        book = select_plaza_rates_book(txn_d, cutover)
        gap = lookup_single_rate(entity_name, book, correct_idx) - lookup_single_rate(
            entity_name, book, npci_idx
        )
        values.append(gap)

    if unknown:
        raise RuntimeError(
            f"[{sheet_label}] Vehicle class(es) not in tc_class_index_map — "
            "add aliases to e5_config.json: "
            + ", ".join(sorted(repr(v) for v in unknown))
        )

    out["NPCI_class_index"] = npci_indexes
    out["Correct_class_index"] = correct_indexes
    out["Exception Value"] = values
    filled = sum(1 for v in values if v is not None)
    total = sum(float(v or 0) for v in values)
    print(
        f"[{sheet_label}] Exception Value on {filled:,}/{len(out):,} rows "
        f"(Correct rate - NPCI rate), sum={total:,.2f}"
    )
    return out


def normalize_key(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().upper()
    if text in {"", "NAN", "NONE", "NAT"}:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text)


def resolve_column(df: pd.DataFrame, preferred: str, aliases: list[str]) -> str:
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    for name in aliases:
        text = str(name).strip()
        if text and text not in candidates:
            candidates.append(text)
    lookup = {str(c).strip().casefold(): c for c in df.columns}
    for name in candidates:
        hit = lookup.get(name.casefold())
        if hit is not None:
            return hit
    raise KeyError(
        "Header keyword not found: "
        + ", ".join(repr(c) for c in candidates)
        + f". Available columns: {list(df.columns)}. "
        "Job stopped — no column mapping is applied."
    )


def load_input(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(path, dtype=str)
    df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]
    return df.dropna(how="all").reset_index(drop=True)


def split_by_charged_class(
    df: pd.DataFrame,
    charged_col: str,
    upto_classes: list[str],
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
    allowed = {normalize_key(v) for v in upto_classes if normalize_key(v)}
    keys = df[charged_col].map(normalize_key)
    upto = df.loc[keys.isin(allowed)].copy().reset_index(drop=True)
    above = df.loc[~keys.isin(allowed)].copy().reset_index(drop=True)
    # Blank charged class stays on the 2-axel sheet so it is still reviewed.
    print(
        f"Split on {charged_col!r}: "
        f"{SHEET_UPTO_LCV}={len(upto):,} "
        f"({', '.join(upto_classes)}); "
        f"{SHEET_TWO_AXLE}={len(above):,}"
    )
    return upto, above


def unique_vehicle_frame(df: pd.DataFrame, vehicle_col: str) -> pd.DataFrame:
    work = df[[vehicle_col]].copy()
    work["_key"] = work[vehicle_col].map(normalize_key)
    work = (
        work.loc[work["_key"].ne("")]
        .drop_duplicates(subset=["_key"], keep="first")
        .drop(columns=["_key"])
        .reset_index(drop=True)
    )
    return work


def class_index_for(value, index_lookup: dict[str, int]) -> int | None:
    key = normalize_value_key(value)
    if not key:
        return None
    return index_lookup.get(key)


def indexes_match(left_class: str, right_class: str, index_lookup: dict[str, int]) -> bool:
    """True when both labels resolve to the same tc_class_index_map index."""
    left_idx = class_index_for(left_class, index_lookup)
    right_idx = class_index_for(right_class, index_lookup)
    if left_idx is None or right_idx is None:
        return False
    return left_idx == right_idx


def scrape_legacy(vehicle_df: pd.DataFrame, vehicle_col: str, scrape_cfg: dict) -> pd.DataFrame:
    """IHMCL scrape via IHMCL_bot.py (USE_SELENIUM=False)."""
    from IHMCL_bot import scrape_ihmcl_for_dataframe

    print(f"Legacy scrape (IHMCL_bot): {len(vehicle_df)} unique VRN(s)")
    return scrape_ihmcl_for_dataframe(
        vehicle_df,
        vehicle_column_names=[vehicle_col, *VEHICLE_COLUMN_ALIASES],
        mobile_number=scrape_cfg.get("mobile_number", "9999999999"),
        plaza_name=scrape_cfg.get("plaza_name", "Phulwaria Toll Plaza"),
    )


def scrape_selenium_local(
    vehicle_df: pd.DataFrame,
    vehicle_col: str,
    scrape_cfg: dict,
) -> pd.DataFrame:
    """IHMCL scrape via local Selenium Chrome (USE_SELENIUM=True, grid off)."""
    from IHMCL_bot_selenium import scrape_ihmcl_for_dataframe

    print(f"Selenium local scrape: {len(vehicle_df)} unique VRN(s)")
    return scrape_ihmcl_for_dataframe(
        vehicle_df,
        vehicle_column_names=[vehicle_col, *VEHICLE_COLUMN_ALIASES],
        mobile_number=scrape_cfg.get("mobile_number", "9999999999"),
        plaza_name=scrape_cfg.get("plaza_name", "Phulwaria Toll Plaza"),
        remote_url=None,
        headless=bool(scrape_cfg.get("headless", False)),
    )


def scrape_via_grid(
    vehicle_df: pd.DataFrame,
    vehicle_col: str,
    scrape_cfg: dict,
) -> pd.DataFrame:
    from IHMCL_bot_selenium import scrape_ihmcl_for_dataframe
    from selenium_grid_manager import (
        assert_grid_ready,
        split_dataframe,
        start_managed_nodes,
        stop_managed_nodes,
        wait_for_grid_ready,
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
                vehicle_column_names=[vehicle_col, *VEHICLE_COLUMN_ALIASES],
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


def scrape_vehicles(
    vehicle_df: pd.DataFrame,
    vehicle_col: str,
    scrape_cfg: dict,
) -> pd.DataFrame:
    """Dispatch IHMCL scrape based on USE_SELENIUM / USE_SELENIUM_GRID."""
    if not USE_SELENIUM:
        return scrape_legacy(vehicle_df, vehicle_col, scrape_cfg)
    if USE_SELENIUM_GRID:
        return scrape_via_grid(vehicle_df, vehicle_col, scrape_cfg)
    return scrape_selenium_local(vehicle_df, vehicle_col, scrape_cfg)


def mark_matches(
    above_df: pd.DataFrame,
    scraped_df: pd.DataFrame,
    vehicle_col: str,
    correct_col: str,
    index_lookup: dict[str, int],
) -> pd.DataFrame:
    """
    Keep every 2-axel row; set Matched=yes when Correct Vehicle Class and
    IHMCL Mapper Vehicle Class share the same tc_class_index_map index.
    """
    out = above_df.copy()
    out["Matched"] = ""
    out["ihmcl_vehicle_number"] = ""
    out["ihmcl_mapper_vehicle_class"] = ""
    out["ihmcl_mapper_class_index"] = None

    if scraped_df is None or scraped_df.empty:
        print("No scraped rows — Matched left blank.")
        return out

    sc_veh = resolve_column(
        scraped_df,
        "Vehicle Number",
        ["Vehicle Number", "Veh Reg No.", "Veh Reg No", vehicle_col],
    )
    sc_cls = resolve_column(
        scraped_df,
        "Mapper Vehicle Class",
        ["Mapper Vehicle Class", "Mapper VC", "Mapper Class"],
    )

    left = out.copy()
    left["_join_key"] = left[vehicle_col].map(normalize_key)
    right = scraped_df.copy()
    right["_join_key"] = right[sc_veh].map(normalize_key)
    right = right[right["_join_key"].ne("")]

    scrape_keep = (
        right[["_join_key", sc_veh, sc_cls]]
        .rename(
            columns={
                sc_veh: "ihmcl_vehicle_number",
                sc_cls: "ihmcl_mapper_vehicle_class",
            }
        )
        .drop_duplicates(subset=["_join_key"], keep="first")
    )
    merged = left.drop(
        columns=[
            "ihmcl_vehicle_number",
            "ihmcl_mapper_vehicle_class",
            "ihmcl_mapper_class_index",
        ],
        errors="ignore",
    ).merge(scrape_keep, on="_join_key", how="left")

    unknown_mapper: set[str] = set()
    mapper_indexes: list[int | None] = []
    matched_flags: list[str] = []
    for correct_raw, mapper_raw in zip(
        merged[correct_col].tolist(),
        merged["ihmcl_mapper_vehicle_class"].tolist(),
    ):
        mapper_text = "" if mapper_raw is None or (isinstance(mapper_raw, float) and pd.isna(mapper_raw)) else str(mapper_raw).strip()
        mapper_idx = class_index_for(mapper_text, index_lookup) if mapper_text else None
        if mapper_text and mapper_idx is None:
            unknown_mapper.add(mapper_text)
        mapper_indexes.append(mapper_idx)
        matched_flags.append(
            "yes"
            if indexes_match(correct_raw, mapper_text, index_lookup)
            else ""
        )

    if unknown_mapper:
        raise RuntimeError(
            "IHMCL Mapper Vehicle Class value(s) not in tc_class_index_map — "
            "add aliases to e5_config.json: "
            + ", ".join(sorted(repr(v) for v in unknown_mapper))
        )

    merged["Matched"] = matched_flags
    merged["ihmcl_vehicle_number"] = merged["ihmcl_vehicle_number"].fillna("")
    merged["ihmcl_mapper_vehicle_class"] = merged["ihmcl_mapper_vehicle_class"].fillna("")
    merged["ihmcl_mapper_class_index"] = mapper_indexes

    yes_count = int((merged["Matched"] == "yes").sum())
    scraped_join = int(merged["ihmcl_mapper_vehicle_class"].astype(str).str.strip().ne("").sum())
    print(
        f"Class-index compare {correct_col!r} vs IHMCL mapper: "
        f"{scraped_join:,}/{len(merged):,} rows had scrape data; "
        f"Matched=yes on {yes_count:,}"
    )
    return merged.drop(columns=["_join_key"]).reset_index(drop=True)


def save_workbook(
    upto_df: pd.DataFrame,
    above_df: pd.DataFrame,
    output_dir: Path = OUTPUT_DIR,
    *,
    file_name: str | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / (file_name or f"invalid_lookup_{stamp}.xlsx")
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        upto_df.to_excel(writer, sheet_name=SHEET_UPTO_LCV, index=False)
        above_df.to_excel(writer, sheet_name=SHEET_TWO_AXLE, index=False)
    return path


def filter_two_axle_for_upload(above_df: pd.DataFrame) -> pd.DataFrame:
    """Keep only Matched=yes on 2-axel sheet (drop empty / No / other)."""
    if above_df is None or above_df.empty:
        return pd.DataFrame() if above_df is None else above_df.copy()
    work = above_df.copy()
    if "Matched" not in work.columns:
        print(
            f"WARNING: no Matched column on {SHEET_TWO_AXLE!r} — "
            "upload sheet will be empty."
        )
        return work.iloc[0:0].copy()
    matched = work["Matched"].astype(str).str.strip().str.casefold()
    # Treat literal "nan" / "none" / "nat" from empty cells as unmatched.
    emptyish = matched.isin({"", "nan", "none", "nat", "null", "na"})
    keep = matched.isin(MATCHED_YES) & ~emptyish
    filtered = work.loc[keep].reset_index(drop=True)
    print(
        f"S3 prep {SHEET_TWO_AXLE}: kept {len(filtered):,}/{len(work):,} "
        "rows with Matched=yes (removed empty/No)."
    )
    return filtered


def resolve_plaza_id(config: dict) -> str:
    plaza_id = str(PLAZA_IDENTIFIER or "").strip()
    if not plaza_id:
        plaza_id = str((config.get("plaza_identifier") or "")).strip()
    if not plaza_id:
        raise RuntimeError(
            "PLAZA_IDENTIFIER is required for DB/S3. "
            "Set it at the top of Main_E5.py "
            "(or plaza_identifier in e5_config.json)."
        )
    return plaza_id


def main() -> int:
    apply_website_env_overrides()
    print("=" * 60)
    print("E5 — Invalid lookup query")
    print(f"INPUT_FILE = {INPUT_FILE}")
    print(f"ENTITY_NAME = {ENTITY_NAME!r}")
    print(f"USE_SELENIUM = {USE_SELENIUM}")
    print(f"USE_SELENIUM_GRID = {USE_SELENIUM_GRID}")
    print(f"SKIP_SCRAPE = {SKIP_SCRAPE}")
    print(f"IHMCL_INPUT_FILE = {IHMCL_INPUT_FILE!r}")
    print("=" * 60)

    config = load_config()
    index_lookup = build_tc_class_index_lookup(config.get("tc_class_index_map") or {})
    cutover = parse_rate_cutover_date(config)

    try:
        df = load_input(Path(INPUT_FILE))
        charged_col = resolve_column(df, CHARGED_CLASS_COLUMN, [CHARGED_CLASS_COLUMN])
        correct_col = resolve_column(
            df,
            CORRECT_CLASS_COLUMN,
            [CORRECT_CLASS_COLUMN, "Correct Class", "Correct VC"],
        )
        npci_col = resolve_column(
            df,
            NPCI_CLASS_COLUMN,
            [NPCI_CLASS_COLUMN, "NPCI Class", "NPCI Class Description"],
        )
        vehicle_col = resolve_column(
            df, VEHICLE_COLUMN_ALIASES[0], VEHICLE_COLUMN_ALIASES
        )
    except KeyError as exc:
        raise RuntimeError(str(exc)) from exc
    try:
        date_col = resolve_column(df, DATE_COLUMN_ALIASES[0], DATE_COLUMN_ALIASES)
    except KeyError:
        date_col = None
        print("WARNING: No date column found — using rate cutover book for all rows.")
    print(
        f"Columns: charged={charged_col!r}, npci={npci_col!r}, "
        f"correct={correct_col!r}, vehicle={vehicle_col!r}, date={date_col!r}"
    )
    print(f"Input rows: {len(df):,}")

    upto_df, above_df = split_by_charged_class(df, charged_col, UPTO_LCV_CLASSES)
    out_dir = Path(MERGED_OUTPUT_HINT)
    out_dir.mkdir(parents=True, exist_ok=True)

    ihmcl_path = Path(str(IHMCL_INPUT_FILE).strip()) if str(IHMCL_INPUT_FILE).strip() else None

    if SKIP_SCRAPE and not ihmcl_path:
        print("SKIP_SCRAPE=True — writing split sheets without IHMCL.")
        above_df = above_df.copy()
        above_df["Matched"] = ""
    elif above_df.empty:
        print("No rows on 2-axel sheet — nothing to scrape.")
        above_df = above_df.copy()
        above_df["Matched"] = ""
    elif ihmcl_path is not None:
        if not ihmcl_path.is_file():
            raise RuntimeError(f"IHMCL input file not found: {ihmcl_path}")
        print(f"Using uploaded IHMCL file (no live scrape): {ihmcl_path}")
        scraped = load_input(ihmcl_path)
        try:
            # Ensure expected scrape columns exist (extra columns OK).
            resolve_column(
                scraped,
                "Vehicle Number",
                ["Vehicle Number", "Veh Reg No.", "Licence Plate No", *VEHICLE_COLUMN_ALIASES],
            )
            resolve_column(
                scraped,
                "Mapper Vehicle Class",
                [
                    "Mapper Vehicle Class",
                    "IHMCL Mapper Vehicle Class",
                    "Mapper Class",
                ],
            )
        except KeyError as exc:
            raise RuntimeError(str(exc)) from exc
        above_df = mark_matches(
            above_df,
            scraped,
            vehicle_col,
            correct_col,
            index_lookup,
        )
    else:
        scrape_cfg = load_scrape_config()
        unique_df = unique_vehicle_frame(above_df, vehicle_col)
        print(f"Unique VRNs to scrape (2-axel and above): {len(unique_df):,}")
        if unique_df.empty:
            above_df = above_df.copy()
            above_df["Matched"] = ""
        else:
            scraped = scrape_vehicles(unique_df, vehicle_col, scrape_cfg)
            if scraped is None:
                scraped = pd.DataFrame()
            print(f"Scraped rows: {len(scraped):,}")

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            scrape_path = out_dir / f"invalid_lookup_ihmcl_{stamp}.xlsx"
            scraped.to_excel(scrape_path, index=False)
            print(f"IHMCL scrape saved: {scrape_path}")

            above_df = mark_matches(
                above_df,
                scraped,
                vehicle_col,
                correct_col,
                index_lookup,
            )

    upto_df = add_exception_values(
        upto_df,
        npci_col=npci_col,
        correct_col=correct_col,
        date_col=date_col,
        index_lookup=index_lookup,
        entity_name=ENTITY_NAME,
        cutover=cutover,
        sheet_label=SHEET_UPTO_LCV,
    )
    above_df = add_exception_values(
        above_df,
        npci_col=npci_col,
        correct_col=correct_col,
        date_col=date_col,
        index_lookup=index_lookup,
        entity_name=ENTITY_NAME,
        cutover=cutover,
        sheet_label=SHEET_TWO_AXLE,
    )

    out_path = save_workbook(upto_df, above_df, output_dir=out_dir)
    print("=" * 60)
    print(f"Wrote: {out_path}")
    print(f"  {SHEET_UPTO_LCV}: {len(upto_df):,} rows")
    print(f"  {SHEET_TWO_AXLE}: {len(above_df):,} rows")
    if "Matched" in above_df.columns:
        print(f"  Matched=yes: {int((above_df['Matched'] == 'yes').sum()):,}")
    print("=" * 60)

    from invalid_lookup_db_update import (
        aggregate_invalid_lookup_workbook,
        upsert_invalid_lookup_monthly,
    )

    # Monthly totals used for metrics DB (all months) and S3 month-year label.
    monthly = aggregate_invalid_lookup_workbook(
        {SHEET_UPTO_LCV: upto_df, SHEET_TWO_AXLE: above_df}
    )
    dry_run = bool(DB_DRY_RUN) or bool(config.get("db_dry_run", False))

    if UPDATE_DB:
        plaza_id = resolve_plaza_id(config)
        print("-" * 60)
        print(
            f"Updating audit_exception_metrics (exception_type_id=5) "
            f"for {len(monthly)} month(s)…"
        )
        upsert_invalid_lookup_monthly(
            monthly,
            plaza_id,
            exception_type_id=int(EXCEPTION_TYPE_ID),
            dry_run=dry_run,
        )
    else:
        print("UPDATE_DB=False — audit_exception_metrics not updated.")

    if not UPLOAD_OUTPUT_TO_S3:
        print("UPLOAD_OUTPUT_TO_S3=False — output file not uploaded.")
        return 0

    plaza_id = resolve_plaza_id(config)
    if not monthly:
        raise RuntimeError(
            "No months with Impact data — cannot build S3 month_label. "
            "Check Reader Read Time / Impact on the output sheets."
        )
    month_periods = [(int(row["year"]), int(row["month"])) for row in monthly]
    label = month_label_from_periods(month_periods)

    filtered_above = filter_two_axle_for_upload(above_df)
    upload_path = save_workbook(
        upto_df,
        filtered_above,
        file_name=f"invalid_lookup_s3_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    )
    print("-" * 60)
    print(
        f"Uploading {upload_path.name} to S3 "
        f"(month_label={label!r}, months={len(month_periods)})…"
    )
    upload_exception_output(
        upload_path,
        plaza_id,
        exception_type_id=int(EXCEPTION_TYPE_ID),
        month_label=label,
        dry_run=dry_run,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
