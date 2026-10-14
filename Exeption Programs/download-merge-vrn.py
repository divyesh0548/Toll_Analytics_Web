"""
Download VRN files from the submissions table and merge selected columns.

Uses the same download path as E4 (Source_DB / submissions.vrn_file_url).
Keeps only columns required by E15 (E15_config.json → vrn_merge.merge_columns):

  Veh Reg No., Date & Time, Lane No, TC Class (from MVC),
  PAYMENT METHOD, SVC FARE, DESCRIPTION, CCH TRANSACTION ID

  Journey Type is not in VRN files — E15 defaults it to single.

Inputs (edit below or pass CLI flags):
  ENTITY_NAME, FROM_DATE, TO_DATE  (YYYY-MM-DD)

Run:
  python download-merge-vrn.py
  python download-merge-vrn.py --entity bassi --from 2026-08-01 --to 2026-08-31
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import psycopg2

BASE_DIR = Path(__file__).resolve().parent
E4_VRN_PATH = BASE_DIR / "E4" / "vrn-download-merge.py"
E15_CONFIG_PATH = BASE_DIR / "E15" / "E15_config.json"

# --- Runtime inputs ---
ENTITY_NAME = "aroli"
FROM_DATE = "2026-09-01"
TO_DATE = "2026-09-30"

DOWNLOAD_FOLDER = BASE_DIR / "vrn_downloads"
OUTPUT_DIR = BASE_DIR / "output"
SKIP_EXISTING = True
# Keep raw downloaded files after merge (True) or delete them (False).
KEEP_DOWNLOADS = True


def _load_e4_vrn():
    path = E4_VRN_PATH
    if not path.is_file():
        raise FileNotFoundError(f"E4 VRN module not found: {path}")
    spec = importlib.util.spec_from_file_location("e4_vrn_download_merge", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_e15_vrn_merge_config() -> dict:
    """E15 merge column map + header detection settings."""
    if not E15_CONFIG_PATH.is_file():
        raise FileNotFoundError(f"E15 config not found: {E15_CONFIG_PATH}")
    with E15_CONFIG_PATH.open(encoding="utf-8") as handle:
        full = json.load(handle)
    vrn = dict(full.get("vrn_merge") or {})
    merge_columns = vrn.get("merge_columns") or {}
    if not merge_columns:
        raise RuntimeError(
            f"{E15_CONFIG_PATH.name} vrn_merge.merge_columns is empty."
        )
    return {
        "header_keywords": list(
            vrn.get("header_keywords") or full.get("header_keywords") or []
        ),
        "header_scan_rows": int(vrn.get("header_scan_rows") or 25),
        "min_header_matches": int(vrn.get("min_header_matches") or 3),
        "merge_columns": merge_columns,
    }


def resolve_date_order(vrn_mod, entity_name: str) -> str:
    """Use E4 entity date_format when set; otherwise leave dates as read."""
    try:
        order = vrn_mod.date_order_for(entity_name, vrn_mod.load_config())
        print(f"VRN date order for {entity_name}: {order}")
        return order
    except RuntimeError as exc:
        print(f"{exc} Date & Time values are kept as read.")
        return ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and merge VRN files (E15 column set)."
    )
    parser.add_argument(
        "--entity",
        default="",
        help=f"submissions entity_name (default: {ENTITY_NAME!r})",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        default="",
        help=f"start date YYYY-MM-DD (default: {FROM_DATE!r})",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        default="",
        help=f"end date YYYY-MM-DD (default: {TO_DATE!r})",
    )
    parser.add_argument(
        "--download-dir",
        default="",
        help="folder for raw VRN downloads",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="folder for merged CSV",
    )
    parser.add_argument(
        "--keep-downloads",
        action="store_true",
        default=None,
        help="keep raw downloads after merge",
    )
    parser.add_argument(
        "--delete-downloads",
        action="store_true",
        help="delete raw downloads after merge",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    entity_name = str(args.entity or ENTITY_NAME).strip()
    from_date = str(args.from_date or FROM_DATE).strip()
    to_date = str(args.to_date or TO_DATE).strip()
    if not entity_name:
        raise RuntimeError("Set ENTITY_NAME or pass --entity.")
    if not from_date or not to_date:
        raise RuntimeError("Set FROM_DATE / TO_DATE or pass --from / --to.")

    download_dir = Path(args.download_dir or DOWNLOAD_FOLDER)
    output_dir = Path(args.output_dir or OUTPUT_DIR)
    if args.delete_downloads:
        keep_downloads = False
    elif args.keep_downloads:
        keep_downloads = True
    else:
        keep_downloads = KEEP_DOWNLOADS

    vrn = _load_e4_vrn()
    merge_cfg = load_e15_vrn_merge_config()
    columns = list(merge_cfg["merge_columns"].keys())

    print("=" * 60)
    print("Download + merge VRN (E15 columns)")
    print(f"ENTITY_NAME = {entity_name!r}")
    print(f"FROM_DATE   = {from_date}")
    print(f"TO_DATE     = {to_date}")
    print(f"Columns ({len(columns)}): {', '.join(columns)}")
    print(f"Download → {download_dir}")
    print(f"Output   → {output_dir}")
    print("=" * 60)

    vrn.load_env()
    start, end = vrn.validate_interval(from_date, to_date)
    date_order = resolve_date_order(vrn, entity_name)

    download_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Connecting to submissions DB…")
    with psycopg2.connect(**vrn.connection_kwargs()) as conn:
        local_paths, stats = vrn.download_vrn_files(
            conn,
            entity_name=entity_name,
            start=start,
            end=end,
            output_folder=download_dir,
            skip_existing=SKIP_EXISTING,
        )

    if not local_paths:
        raise FileNotFoundError(
            f"No VRN files for entity={entity_name!r} "
            f"{start.isoformat()} → {end.isoformat()} "
            f"(found={stats.get('found', 0)}, failed={stats.get('failed', 0)})"
        )

    merged_name = (
        f"{vrn.safe_part(entity_name)}_"
        f"{start.isoformat()}_{end.isoformat()}_merged_vrn.csv"
    )
    merged_path = vrn.merge_vrn_files(
        local_paths,
        merge_cfg,
        output_dir / merged_name,
        date_order,
    )

    if keep_downloads:
        print(f"Keeping {len(local_paths)} downloaded file(s) under {download_dir}")
    else:
        vrn.delete_downloaded_files(local_paths, download_dir)

    print("-" * 60)
    print(f"Done. Merged file: {merged_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
