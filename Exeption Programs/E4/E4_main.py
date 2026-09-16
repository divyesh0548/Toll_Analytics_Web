"""
E4 — Pass file merge (step 1).

Reads all Pass Excel/CSV files from a folder, detects the header row using
keywords from config.json, verifies every file shares the same header, and
merges them into one Excel (first sheet only for workbooks).

config.json is mappings/aliases only (header keywords, column aliases, etc.).
Runtime paths are set as variables below.

Run:
  1. Set PASS_INPUT_FOLDER (and optionally MERGED_OUTPUT_FILE) below
  2. python E4_main.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

# --- Runtime inputs (edit these; not in config.json) ---
PASS_INPUT_FOLDER = r"C:\Divyesh\Toll Analytics Dashboard\Exeption Programs\E4\Pass"  # e.g. r"C:\path\to\pass\files"
MERGED_OUTPUT_FILE = BASE_DIR / "output" / "merged_pass_files.xlsx"
EXCEL_EXTENSIONS = [".xlsx", ".xls", ".xlsm", ".csv"]


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def list_pass_files(folder: Path, extensions: list[str]) -> list[Path]:
    exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions}
    files = sorted(
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in exts and not p.name.startswith("~$")
    )
    return files


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
        raise ValueError("header_keywords is empty in config.json")

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
            f"Header row not detected (need >= {min_matches} keyword matches; "
            f"best score={best_score})."
        )
    return best_idx


def read_first_sheet_raw(path: Path) -> pd.DataFrame:
    """Load first sheet (or CSV) with no header so we can locate it ourselves."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    # sheet_name=0 → first sheet only
    return pd.read_excel(path, sheet_name=0, header=None, dtype=str)


def dataframe_from_header(
    df_raw: pd.DataFrame,
    header_idx: int,
) -> tuple[list[str], pd.DataFrame]:
    headers = [_normalize_header_cell(v) for v in df_raw.iloc[header_idx].tolist()]
    # Drop trailing empty header names that come from blank columns
    while headers and headers[-1] == "":
        headers.pop()
    if not any(headers):
        raise ValueError("Detected header row is empty")

    body = df_raw.iloc[header_idx + 1 :, : len(headers)].copy()
    body.columns = headers
    body = body.dropna(how="all").reset_index(drop=True)
    return headers, body


def header_signature(headers: list[str]) -> tuple[str, ...]:
    return tuple(_normalize_header_key(h) for h in headers)


def load_pass_file(
    path: Path,
    *,
    keywords: list[str],
    scan_rows: int,
    min_matches: int,
) -> tuple[list[str], pd.DataFrame]:
    print(f"Reading: {path.name}")
    df_raw = read_first_sheet_raw(path)
    if df_raw.empty:
        raise ValueError(f"File is empty: {path.name}")

    header_idx = detect_header_row(
        df_raw,
        keywords,
        scan_rows=scan_rows,
        min_matches=min_matches,
    )
    headers, df = dataframe_from_header(df_raw, header_idx)
    print(f"  Header at row {header_idx + 1} ({len(headers)} columns, {len(df)} data rows)")
    return headers, df


def merge_pass_folder(config: dict) -> Path:
    folder_raw = str(PASS_INPUT_FOLDER or "").strip()
    if not folder_raw:
        raise RuntimeError("Set PASS_INPUT_FOLDER at the top of E4_main.py")

    folder = Path(folder_raw)
    if not folder.is_dir():
        raise FileNotFoundError(f"Pass input folder not found: {folder}")

    files = list_pass_files(folder, EXCEL_EXTENSIONS)
    if not files:
        raise FileNotFoundError(f"No Pass files found in: {folder}")

    keywords = config.get("header_keywords") or []
    scan_rows = int(config.get("header_scan_rows") or 25)
    min_matches = int(config.get("min_header_matches") or 3)

    print(f"Folder: {folder}")
    print(f"Files found: {len(files)}")
    print("=" * 60)

    reference_headers: list[str] | None = None
    reference_signature: tuple[str, ...] | None = None
    reference_file: str | None = None
    frames: list[pd.DataFrame] = []

    for path in files:
        headers, df = load_pass_file(
            path,
            keywords=keywords,
            scan_rows=scan_rows,
            min_matches=min_matches,
        )
        signature = header_signature(headers)

        if reference_signature is None:
            reference_headers = headers
            reference_signature = signature
            reference_file = path.name
        elif signature != reference_signature:
            raise RuntimeError(
                "Header mismatch — all Pass files must share the same header row.\n"
                f"  Reference file : {reference_file}\n"
                f"  Reference cols : {reference_headers}\n"
                f"  Current file   : {path.name}\n"
                f"  Current cols   : {headers}\n"
                "Execution stopped."
            )

        # Force identical column names (preserve first file's display casing).
        df = df.copy()
        df.columns = list(reference_headers)
        df["__source_file"] = path.name
        frames.append(df)

    merged = pd.concat(frames, ignore_index=True)
    print("=" * 60)
    print(f"Merged rows: {len(merged)} from {len(frames)} file(s)")

    output_path = Path(MERGED_OUTPUT_FILE)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_excel(output_path, index=False)
    print(f"Wrote: {output_path}")
    return output_path


def main() -> int:
    config = load_config()
    merge_pass_folder(config)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
