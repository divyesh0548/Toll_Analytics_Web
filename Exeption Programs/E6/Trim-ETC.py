"""
Trim-ETC — keep only the first N data rows of an ETC Excel/CSV.

Preserves all rows above the detected header (titles/meta), the header row
itself, then the first ROW_LIMIT data rows.

Runtime inputs are variables below (not config). Header keywords come from
e6_config.json.

Run:
  1. Set INPUT_FILE / OUTPUT_FILE / ROW_LIMIT below
  2. python Trim-ETC.py
     or: python Trim-ETC.py 5000
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "e6_config.json"

# --- Runtime inputs (edit these) ---
INPUT_FILE = BASE_DIR / "input" / "odhaki_etc_trimmed_Apr_26.xlsx"
OUTPUT_FILE = BASE_DIR / "output" / "etc_trimmed.xlsx"
ROW_LIMIT = 2000  # keep first N data rows after the header


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
    keyword_keys = {_normalize_header_key(k) for k in keywords if str(k).strip()}
    if not keyword_keys:
        raise ValueError("header_keywords is empty in e6_config.json")

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
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    return pd.read_excel(path, sheet_name=0, header=None, dtype=str)


def resolve_row_limit(default: int) -> int:
    if len(sys.argv) >= 2:
        raw = str(sys.argv[1]).strip()
    else:
        raw = str(default)
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ValueError(f"ROW_LIMIT must be an integer, got: {raw!r}") from exc
    if limit < 0:
        raise ValueError(f"ROW_LIMIT must be >= 0, got: {limit}")
    return limit


def trim_etc(input_path: Path, output_path: Path, row_limit: int) -> Path:
    config = load_config()
    keywords = config.get("header_keywords") or []
    scan_rows = int(config.get("header_scan_rows") or 25)
    min_matches = int(config.get("min_header_matches") or 3)

    df_raw = read_etc_raw(input_path)
    if df_raw.empty:
        raise ValueError(f"File is empty: {input_path}")

    header_idx = detect_header_row(
        df_raw,
        keywords,
        scan_rows=scan_rows,
        min_matches=min_matches,
    )
    headers = [_normalize_header_cell(v) for v in df_raw.iloc[header_idx].tolist()]
    while headers and headers[-1] == "":
        headers.pop()

    data_start = header_idx + 1
    data_end = min(data_start + row_limit, len(df_raw))
    trimmed = df_raw.iloc[:data_end].copy()

    kept_data = max(0, data_end - data_start)
    print(f"Input:  {input_path}")
    print(f"Header: row {header_idx + 1} (0-based index={header_idx})")
    print(f"Columns ({len(headers)}): {headers}")
    print(f"Original data rows: {max(0, len(df_raw) - data_start)}")
    print(f"Kept data rows:     {kept_data} (limit={row_limit})")
    print(f"Total rows written: {len(trimmed)} (including preamble + header)")

    output_path = Path(output_path)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.suffix.lower() == ".csv":
        trimmed.to_csv(output_path, index=False, header=False)
    else:
        trimmed.to_excel(output_path, index=False, header=False)

    print(f"Wrote: {output_path}")
    return output_path


def main() -> int:
    row_limit = resolve_row_limit(ROW_LIMIT)
    print("=" * 60)
    print("Trim-ETC")
    print(f"ROW_LIMIT = {row_limit}")
    print("=" * 60)
    trim_etc(Path(INPUT_FILE), Path(OUTPUT_FILE), row_limit)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}")
        sys.exit(1)
