"""
DEPRECATED — use run_plaza_etl.py instead.

Updates "gap_distribution_per_lane" with hourly avg gap and <2s counts per lane.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from config.db import (
    ensure_gap_distribution_table,
    get_analytics_db_connection_kwargs,
)
from config.excel_config import (
    COLUMN_MAPPING,
    GAP_REQUIRED_FIELDS,
    LANE_COLUMNS,
    LANE_LT2_COLUMNS,
)
from config.settings import (
    GAP_DISTRIBUTION_TABLE,
    INPUT_FOLDER,
    PLAZA_IDENTIFIER,
    PLAZA_NAME,
    START_DATE_LIMIT,
    START_DATE_LIMIT_DATE,
)
from excel_common import (
    UnmappedValueError,
    append_run_log,
    create_run_log_file,
    detect_datetime_format,
    find_column,
    hour_bucket_label,
    is_blank,
    is_header_detection_error,
    lane_limit_error_message,
    list_excel_files,
    optional_normalize_lane,
    read_excel_file,
    safe_parse_datetime,
    try_normalize_lane,
    try_parse_datetime,
    unsupported_high_lane_counts,
)

DRY_RUN = False

# Gaps strictly below this threshold (seconds) are counted as potential tailgating.
GAP_LT_2S_THRESHOLD = 2.0

DATA_COLUMNS = [
    "plaza_identifier",
    "plaza_name",
    "date",
    "hour",
    *LANE_COLUMNS.values(),
    *LANE_LT2_COLUMNS.values(),
]


def require_plaza_settings() -> None:
    if not PLAZA_IDENTIFIER or PLAZA_IDENTIFIER == "REPLACE_WITH_PLAZA_UUID":
        raise RuntimeError(
            "Set PLAZA_IDENTIFIER in Plaza_db_update/config/settings.py "
            "to the plaza UUID from the website."
        )
    if not PLAZA_NAME or not str(PLAZA_NAME).strip():
        raise RuntimeError("Set PLAZA_NAME in Plaza_db_update/config/settings.py.")


def average_or_none(values: np.ndarray) -> float | None:
    if values.size == 0:
        return None
    return float(np.mean(values))


def validate_dataframe(
    df: pd.DataFrame,
    file_name: str,
    datetime_format: str,
) -> list[str]:
    datetime_col = find_column(df, COLUMN_MAPPING["datetime"])
    lane_col = find_column(df, COLUMN_MAPPING["lane_no"])

    invalid_datetimes: dict[str, int] = {}
    unmapped_lanes: dict[str, int] = {}
    raw_lanes: list = []

    for _row_idx, row in df.iterrows():
        datetime_value = row[datetime_col]
        if not is_blank(datetime_value):
            if try_parse_datetime(datetime_value, datetime_format=datetime_format) is None:
                raw_dt = str(datetime_value).strip()
                invalid_datetimes[raw_dt] = invalid_datetimes.get(raw_dt, 0) + 1

        lane_value = row[lane_col]
        if not is_blank(lane_value):
            raw_lanes.append(lane_value)
            if try_normalize_lane(lane_value) is None:
                raw_lane = str(lane_value).strip()
                unmapped_lanes[raw_lane] = unmapped_lanes.get(raw_lane, 0) + 1

    errors: list[str] = []
    if invalid_datetimes:
        errors.append(
            f"Invalid datetime values in '{file_name}' ({datetime_col}): "
            + ", ".join(f"{value!r} ({count} row(s))" for value, count in sorted(invalid_datetimes.items()))
        )

    high_lanes = unsupported_high_lane_counts(raw_lanes)
    if high_lanes:
        errors.append(lane_limit_error_message(file_name, lane_col, high_lanes))

    if unmapped_lanes:
        remaining = {
            value: count
            for value, count in unmapped_lanes.items()
            if value not in high_lanes
        }
        if remaining:
            errors.append(
                f"Unmapped lane values in '{file_name}' ({lane_col}): "
                + ", ".join(f"{value!r} ({count} row(s))" for value, count in sorted(remaining.items()))
            )
    return errors


def print_validation_errors(errors: list[str]) -> None:
    print("\n" + "=" * 80)
    print("VALIDATION FAILED — abnormal data found. DB insertion skipped.")
    print("=" * 80)
    for error in errors:
        print(f"  - {error}")
    print("=" * 80)


def prepare_dataframe(df: pd.DataFrame, datetime_format: str) -> pd.DataFrame:
    datetime_col = find_column(df, COLUMN_MAPPING["datetime"])
    lane_col = find_column(df, COLUMN_MAPPING["lane_no"])

    prepared = pd.DataFrame()
    prepared["event_dt"] = df[datetime_col].map(
        lambda value: safe_parse_datetime(value, datetime_format)
    )
    prepared["lane_no"] = df[lane_col].map(optional_normalize_lane)
    prepared = prepared[prepared["event_dt"].notna() & prepared["lane_no"].notna()].copy()
    prepared["hour"] = prepared["event_dt"].map(hour_bucket_label)
    prepared["date"] = prepared["event_dt"].dt.date
    prepared = prepared[prepared["date"] >= START_DATE_LIMIT_DATE].copy()
    return prepared


def aggregate_hourly_gap_rows(df: pd.DataFrame) -> list[dict]:
    """One row per plaza + date + hour with per-lane avg gap and <2s counts."""
    if df.empty:
        return []

    ordered = df.sort_values(["lane_no", "event_dt"], kind="mergesort").copy()
    ordered["prev_dt"] = ordered.groupby("lane_no", sort=False)["event_dt"].shift(1)
    ordered["gap_sec"] = (ordered["event_dt"] - ordered["prev_dt"]).dt.total_seconds()
    ordered.loc[ordered["gap_sec"] < 0, "gap_sec"] = np.nan

    hour_keys = ordered.groupby(["date", "hour"], sort=True).size().index
    gap_lookup = {
        key: group.to_numpy(dtype=float, copy=False)
        for key, group in ordered.dropna(subset=["gap_sec"]).groupby(
            ["date", "hour", "lane_no"], sort=True
        )["gap_sec"]
    }

    rows: list[dict] = []
    for record_date, hour_label in hour_keys:
        row: dict = {
            "plaza_identifier": PLAZA_IDENTIFIER,
            "plaza_name": PLAZA_NAME,
            "date": record_date,
            "hour": hour_label,
        }
        for lane, avg_column in LANE_COLUMNS.items():
            gap_values = gap_lookup.get(
                (record_date, hour_label, lane),
                np.array([], dtype=float),
            )
            row[avg_column] = average_or_none(gap_values)
            lt2_column = LANE_LT2_COLUMNS[lane]
            row[lt2_column] = int(
                sum(1 for value in gap_values if float(value) < GAP_LT_2S_THRESHOLD)
            )
        rows.append(row)

    return rows


def print_hourly_rows(rows: list[dict]) -> None:
    if not rows:
        print("  No hourly gap rows prepared.")
        return

    print("\n  Prepared DB rows:")
    print("  " + "-" * 76)
    for index, row in enumerate(rows, start=1):
        print(f"  Row {index}:")
        for key, value in row.items():
            print(f"    {key}: {value}")
    print("  " + "-" * 76)


def fetch_existing_hour_keys(conn, table_name: str, rows: list[dict]) -> set[tuple]:
    if not rows:
        return set()

    keys = [(row["plaza_identifier"], row["date"], row["hour"]) for row in rows]
    query = sql.SQL(
        "SELECT plaza_identifier, date, hour FROM {table} "
        "WHERE (plaza_identifier, date, hour) IN %s"
    ).format(table=sql.Identifier(table_name))

    with conn.cursor() as cursor:
        cursor.execute(query.as_string(conn), (tuple(keys),))
        return {
            (plaza_identifier, record_date, hour)
            for plaza_identifier, record_date, hour in cursor.fetchall()
        }


def upsert_rows(conn, table_name: str, rows: list[dict]) -> tuple[int, int]:
    if not rows:
        return 0, 0

    existing_keys = fetch_existing_hour_keys(conn, table_name, rows)
    rows_to_insert: list[dict] = []
    skipped = 0

    for row in rows:
        key = (row["plaza_identifier"], row["date"], row["hour"])
        if key in existing_keys:
            print(
                f"  SKIP (exists): plaza_id={row['plaza_identifier']}, "
                f"plaza={row['plaza_name']}, date={row['date']}, hour={row['hour']}"
            )
            skipped += 1
        else:
            rows_to_insert.append(row)

    if not rows_to_insert:
        return 0, skipped

    insert_sql = sql.SQL(
        "INSERT INTO {table} ({fields}) VALUES %s"
    ).format(
        table=sql.Identifier(table_name),
        fields=sql.SQL(", ").join(sql.Identifier(column) for column in DATA_COLUMNS),
    )
    values = [tuple(row[column] for column in DATA_COLUMNS) for row in rows_to_insert]

    with conn.cursor() as cursor:
        execute_values(cursor, insert_sql.as_string(conn), values)
    conn.commit()
    return len(rows_to_insert), skipped


def process_file(
    file_path: Path,
    table_name: str,
    conn=None,
    dry_run: bool = False,
    run_log: Path | None = None,
) -> tuple[int, bool]:
    print(f"\nProcessing file: {file_path}")
    try:
        df = read_excel_file(file_path, required_fields=GAP_REQUIRED_FIELDS)
    except ValueError as exc:
        if is_header_detection_error(exc):
            message = f"[SKIP] {file_path} — {exc}"
            print(f"  {message}")
            if run_log is not None:
                append_run_log(run_log, message)
            return 0, True

        print(f"\n  File preparation failed: {exc}")
        raise UnmappedValueError(
            f"File '{file_path.name}' could not be prepared. No rows were inserted."
        ) from exc

    print(f"  Rows read after header detection and normalization: {len(df)}")

    datetime_col = find_column(df, COLUMN_MAPPING["datetime"])
    datetime_format = detect_datetime_format(df[datetime_col].tolist())
    print(f"  Detected datetime format: {datetime_format}")

    validation_errors = validate_dataframe(df, file_path.name, datetime_format)
    if validation_errors:
        print_validation_errors(validation_errors)
        raise UnmappedValueError(
            f"File '{file_path.name}' failed validation. No rows were inserted."
        )

    print("  Validation passed for entire file.")
    prepared = prepare_dataframe(df, datetime_format)
    if prepared.empty:
        print(f"  No rows on or after {START_DATE_LIMIT}. Skipping file.")
        return 0, False

    hourly_rows = aggregate_hourly_gap_rows(prepared)

    if dry_run:
        print("  DRY RUN — skipping DB insert.")
        print_hourly_rows(hourly_rows)
        return len(hourly_rows), False

    print("  Starting DB insertion...")
    inserted, skipped = upsert_rows(conn, table_name, hourly_rows)
    print(f"  Hourly gap rows inserted: {inserted}, skipped (already exists): {skipped}")
    return inserted, False


def process_folder(folder_path: str, dry_run: bool = DRY_RUN) -> None:
    require_plaza_settings()
    folder = Path(folder_path)
    if not folder.is_dir():
        raise FileNotFoundError(f"Input folder not found: {folder_path}")

    table_name = GAP_DISTRIBUTION_TABLE
    files = list_excel_files(folder)
    if not files:
        print(f"No Excel/CSV files found under: {folder} (including subfolders)")
        return

    print(f"Plaza identifier: {PLAZA_IDENTIFIER}")
    print(f"Plaza name: {PLAZA_NAME}")
    print(f"Target database: {get_analytics_db_connection_kwargs()['database']}")
    print(f"Target table: {table_name}")
    print(f"Files found: {len(files)}")

    run_log = create_run_log_file(ROOT_DIR, "module2")
    print(f"Run log: {run_log}")
    append_run_log(
        run_log,
        f"Plaza identifier: {PLAZA_IDENTIFIER}\nPlaza: {PLAZA_NAME}\n"
        f"Input folder: {folder}\nFiles found: {len(files)}",
    )

    if dry_run:
        print("DRY RUN enabled — prepared rows will be printed only.")

    total_rows = 0
    skipped_files = 0
    if dry_run:
        for file_path in files:
            try:
                rows, file_skipped = process_file(
                    file_path,
                    table_name,
                    dry_run=True,
                    run_log=run_log,
                )
                if file_skipped:
                    skipped_files += 1
                total_rows += rows
            except UnmappedValueError:
                append_run_log(run_log, "Execution stopped due to validation failure.")
                print("\nExecution stopped. Fix the abnormal values above and rerun.")
                print(f"See log: {run_log}")
                sys.exit(1)
        append_run_log(
            run_log,
            f"\nDry run complete. Total hourly gap rows prepared: {total_rows}. "
            f"Skipped files: {skipped_files}.",
        )
        print(f"\nDry run complete. Total hourly gap rows prepared: {total_rows}")
        print(f"Skipped files: {skipped_files}. Log: {run_log}")
        return

    conn = psycopg2.connect(**get_analytics_db_connection_kwargs())
    try:
        ensure_gap_distribution_table(
            conn,
            table_name,
            list(LANE_COLUMNS.values()),
            list(LANE_LT2_COLUMNS.values()),
        )
        for file_path in files:
            try:
                rows, file_skipped = process_file(
                    file_path,
                    table_name,
                    conn=conn,
                    dry_run=False,
                    run_log=run_log,
                )
                if file_skipped:
                    skipped_files += 1
                total_rows += rows
            except UnmappedValueError:
                append_run_log(run_log, "Execution stopped due to validation failure.")
                print("\nExecution stopped. Fix the abnormal values above and rerun.")
                print(f"See log: {run_log}")
                sys.exit(1)
        append_run_log(
            run_log,
            f"\nCompleted. Total hourly gap rows inserted: {total_rows}. "
            f"Skipped files: {skipped_files}.",
        )
        print(f"\nCompleted. Total hourly gap rows inserted: {total_rows}")
        print(f"Skipped files: {skipped_files}. Log: {run_log}")
    finally:
        conn.close()


def main() -> None:
    folder_path = INPUT_FOLDER
    if len(sys.argv) > 1:
        folder_path = sys.argv[1].strip().strip('"')

    process_folder(folder_path, dry_run=DRY_RUN)


if __name__ == "__main__":
    main()
