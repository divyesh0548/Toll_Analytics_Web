"""
Scan a folder (including subfolders) for Excel/CSV files and collect distinct
vehicle class, lane, and MOP values into a single text file.

Column names are resolved using the mappings from module1.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from module1 import COLUMN_MAPPING, EXCEL_EXTENSIONS, normalize_key

# ---------------------------------------------------------------------------
# Inputs — update these before running
# ---------------------------------------------------------------------------

INPUT_FOLDER = r"C:\Divyesh\NHIT_dashboard_processing\New Dashboard Insights\Input"
OUTPUT_FILE = SCRIPT_DIR / "Distinct Values" / "distinct_values.txt"

HEADER_SCAN_ROWS = 25

FIELD_COLUMN_ALIASES: dict[str, list[str]] = {
    "vehicle_class": [COLUMN_MAPPING["vehicle_class"], "MVC_TLC_CLASS", "TC Class"],
    "lane_no": [COLUMN_MAPPING["lane_no"], "Lane No"],
    "mop": [COLUMN_MAPPING["mop"], "MVC_TLC_MOP"],
}

FIELD_LABELS: dict[str, str] = {
    "vehicle_class": "Vehicle Class",
    "lane_no": "Lane",
    "mop": "MOP",
}


def list_excel_files(folder_path: Path) -> list[Path]:
    return sorted(
        path
        for path in folder_path.rglob("*")
        if path.is_file()
        and path.suffix.lower() in EXCEL_EXTENSIONS
        and not path.name.startswith("~$")
    )


def read_raw_table(file_path: Path) -> pd.DataFrame:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file_path, header=None, dtype=str)
    return pd.read_excel(file_path, header=None, dtype=str)


def all_column_aliases() -> set[str]:
    aliases: set[str] = set()
    for field_aliases in FIELD_COLUMN_ALIASES.values():
        aliases.update(normalize_key(alias) for alias in field_aliases)
    return aliases


def find_header_row(df: pd.DataFrame, max_rows: int = HEADER_SCAN_ROWS) -> int | None:
    """Pick the row that best matches module1 column names (same idea as module1.py)."""
    targets = all_column_aliases()
    best_row = None
    best_score = 0
    rows_to_scan = min(max_rows, len(df))

    for row_index in range(rows_to_scan):
        row_cells = {
            normalize_key(value)
            for value in df.iloc[row_index]
            if not pd.isna(value) and str(value).strip()
        }
        score = sum(1 for target in targets if target in row_cells)
        if score > best_score:
            best_score = score
            best_row = row_index

    if best_score >= 2:
        return best_row
    return None


def load_dataframe_with_detected_header(file_path: Path) -> tuple[pd.DataFrame, int] | None:
    raw_df = read_raw_table(file_path)
    header_row = find_header_row(raw_df)
    if header_row is None:
        return None

    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(file_path, header=header_row, dtype=str)
    else:
        df = pd.read_excel(file_path, header=header_row, dtype=str)

    df.columns = [str(column).strip() for column in df.columns]
    return df, header_row


def resolve_column_name(df: pd.DataFrame, column_aliases: list[str]) -> str:
    normalized_aliases = [normalize_key(alias) for alias in column_aliases]

    for alias in column_aliases:
        if alias in df.columns:
            return alias

    for column in df.columns:
        if normalize_key(column) in normalized_aliases:
            return column

    available = ", ".join(str(column) for column in df.columns)
    alias_list = ", ".join(column_aliases)
    raise ValueError(
        f"None of [{alias_list}] found after header detection. Available columns: {available}"
    )


def get_distinct_values(df: pd.DataFrame, column_name: str) -> list[str]:
    series = df[column_name].dropna().astype(str).str.strip()
    series = series[series != ""]
    return sorted(series.unique().tolist(), key=lambda value: value.upper())


def collect_distinct_values_from_folder(input_folder: str | Path, output_file: str | Path) -> Path:
    folder = Path(input_folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Input folder not found: {input_folder}")

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    files = list_excel_files(folder)
    if not files:
        raise FileNotFoundError(f"No Excel/CSV files found under: {folder}")

    distinct_by_field: dict[str, set[str]] = {field: set() for field in FIELD_COLUMN_ALIASES}
    processed_counts: dict[str, int] = {field: 0 for field in FIELD_COLUMN_ALIASES}
    skipped_files: list[str] = []

    print(f"Input folder: {folder}")
    print(f"Files found: {len(files)}\n")

    for file_path in files:
        relative_path = file_path.relative_to(folder)
        print(f"Processing: {relative_path}")

        try:
            loaded = load_dataframe_with_detected_header(file_path)
            if loaded is None:
                skipped_files.append(str(relative_path))
                print("  Skipped: header row not found")
                continue

            df, header_row = loaded
            print(f"  Header row: {header_row + 1}")

            for field, aliases in FIELD_COLUMN_ALIASES.items():
                try:
                    resolved_column = resolve_column_name(df, aliases)
                    values = get_distinct_values(df, resolved_column)
                    distinct_by_field[field].update(values)
                    processed_counts[field] += 1
                    print(
                        f"  [{FIELD_LABELS[field]}] column '{resolved_column}', "
                        f"distinct in file: {len(values)}"
                    )
                except ValueError as exc:
                    print(f"  [{FIELD_LABELS[field]}] skipped: {exc}")

        except (ValueError, KeyError) as exc:
            skipped_files.append(str(relative_path))
            print(f"  Skipped: {exc}")

    lines: list[str] = []
    lines.append("Distinct values collected from Excel/CSV files")
    lines.append(f"Input folder: {folder}")
    lines.append(f"Files scanned: {len(files)}")
    lines.append("")

    for field, aliases in FIELD_COLUMN_ALIASES.items():
        lines.append(f"=== {FIELD_LABELS[field]} ===")
        lines.append(f"Column aliases: {', '.join(aliases)}")
        lines.append(f"Files processed: {processed_counts[field]}")
        lines.append("")

        for value in sorted(distinct_by_field[field], key=lambda item: item.upper()):
            lines.append(value)

        lines.append("")

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    print("\nSummary")
    for field in FIELD_COLUMN_ALIASES:
        print(
            f"  {FIELD_LABELS[field]}: {len(distinct_by_field[field])} distinct value(s) "
            f"from {processed_counts[field]} file(s)"
        )
    if skipped_files:
        print(f"  Files fully skipped: {len(skipped_files)}")
    print(f"\nOutput written to: {output_path}")

    return output_path


if __name__ == "__main__":
    folder_path = INPUT_FOLDER
    output_path = OUTPUT_FILE

    if len(sys.argv) > 1:
        folder_path = sys.argv[1]
    if len(sys.argv) > 2:
        output_path = Path(sys.argv[2])

    collect_distinct_values_from_folder(folder_path, output_path)
