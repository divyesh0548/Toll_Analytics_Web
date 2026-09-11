"""
DEPRECATED — use run_plaza_etl.py instead.

Updates "nhit_analytics" table with hourly vehicle count by lane,class and MOP.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from config.db import (
    ensure_analytics_table,
    get_analytics_db_connection_kwargs,
    get_analytics_table_name,
)
from config.excel_config import (
    COLUMN_MAPPING,
    LANE_COLUMNS,
    TOTAL_TRANSACTION_COLUMN,
    VOLUME_REQUIRED_FIELDS,
)
from config.settings import (
    INPUT_FOLDER,
    PLAZA_IDENTIFIER,
    PLAZA_NAME,
    START_DATE_LIMIT,
    START_DATE_LIMIT_DATE,
)
from excel_common import (
    MOP_COLUMNS,
    UnmappedValueError,
    VEHICLE_CLASS_COLUMNS,
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
    optional_normalize_mop,
    optional_normalize_vehicle_class,
    read_excel_file,
    safe_parse_datetime,
    try_normalize_lane,
    try_normalize_mop,
    try_normalize_vehicle_class,
    try_parse_datetime,
    unsupported_high_lane_counts,
)

# If True, print prepared hourly rows only — no DB connection or inserts.
DRY_RUN = False


def require_plaza_settings() -> None:
    if not PLAZA_IDENTIFIER or PLAZA_IDENTIFIER == "REPLACE_WITH_PLAZA_UUID":
        raise RuntimeError(
            "Set PLAZA_IDENTIFIER in Plaza_db_update/config/settings.py "
            "to the plaza UUID from the website."
        )
    if not PLAZA_NAME or not str(PLAZA_NAME).strip():
        raise RuntimeError("Set PLAZA_NAME in Plaza_db_update/config/settings.py.")


def validate_dataframe(
    df: pd.DataFrame,
    file_name: str,
    datetime_format: str,
) -> list[str]:
    """
    Scan the entire file before any DB work.
    Returns a list of validation error messages; empty list means file is safe to insert.
    """
    datetime_col = find_column(df, COLUMN_MAPPING["datetime"])
    vehicle_col = find_column(df, COLUMN_MAPPING["vehicle_class"])
    lane_col = find_column(df, COLUMN_MAPPING["lane_no"])
    mop_col = find_column(df, COLUMN_MAPPING["mop"])

    invalid_datetimes: dict[str, int] = {}
    unmapped_vehicle_classes: dict[str, int] = {}
    unmapped_lanes: dict[str, int] = {}
    unmapped_mops: dict[str, int] = {}
    raw_lanes: list = []

    for _row_idx, row in df.iterrows():
        datetime_value = row[datetime_col]
        if not is_blank(datetime_value):
            if try_parse_datetime(datetime_value, datetime_format=datetime_format) is None:
                raw_dt = str(datetime_value).strip()
                invalid_datetimes[raw_dt] = invalid_datetimes.get(raw_dt, 0) + 1

        vehicle_value = row[vehicle_col]
        if not is_blank(vehicle_value):
            if try_normalize_vehicle_class(vehicle_value) is None:
                raw_vc = str(vehicle_value).strip()
                unmapped_vehicle_classes[raw_vc] = unmapped_vehicle_classes.get(raw_vc, 0) + 1

        lane_value = row[lane_col]
        if not is_blank(lane_value):
            raw_lanes.append(lane_value)
            if try_normalize_lane(lane_value) is None:
                raw_lane = str(lane_value).strip()
                unmapped_lanes[raw_lane] = unmapped_lanes.get(raw_lane, 0) + 1

        mop_value = row[mop_col]
        if not is_blank(mop_value):
            if try_normalize_mop(mop_value) is None:
                raw_mop = str(mop_value).strip()
                unmapped_mops[raw_mop] = unmapped_mops.get(raw_mop, 0) + 1

    errors: list[str] = []
    if invalid_datetimes:
        errors.append(
            f"Invalid datetime values in '{file_name}' ({datetime_col}): "
            + ", ".join(f"{value!r} ({count} row(s))" for value, count in sorted(invalid_datetimes.items()))
        )
    if unmapped_vehicle_classes:
        errors.append(
            f"Unmapped vehicle class values in '{file_name}' ({vehicle_col}): "
            + ", ".join(f"{value!r} ({count} row(s))" for value, count in sorted(unmapped_vehicle_classes.items()))
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
    if unmapped_mops:
        errors.append(
            f"Unmapped MOP values in '{file_name}' ({mop_col}): "
            + ", ".join(f"{value!r} ({count} row(s))" for value, count in sorted(unmapped_mops.items()))
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
    vehicle_col = find_column(df, COLUMN_MAPPING["vehicle_class"])
    lane_col = find_column(df, COLUMN_MAPPING["lane_no"])
    mop_col = find_column(df, COLUMN_MAPPING["mop"])

    prepared = pd.DataFrame()
    prepared["event_dt"] = df[datetime_col].map(
        lambda value: safe_parse_datetime(value, datetime_format)
    )
    prepared["vehicle_class"] = df[vehicle_col].map(optional_normalize_vehicle_class)
    prepared["lane_no"] = df[lane_col].map(optional_normalize_lane)
    prepared["mop"] = df[mop_col].map(optional_normalize_mop)

    prepared = prepared[prepared["event_dt"].notna()].copy()
    prepared["hour"] = prepared["event_dt"].map(hour_bucket_label)
    prepared["date"] = prepared["event_dt"].dt.date
    prepared = prepared[prepared["date"] >= START_DATE_LIMIT_DATE].copy()
    return prepared


def aggregate_hourly_rows(df: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []

    for (record_date, hour_label), group in df.groupby(["date", "hour"], sort=True):
        row = {
            "plaza_identifier": PLAZA_IDENTIFIER,
            "plaza_name": PLAZA_NAME,
            "hour": hour_label,
            "date": record_date,
        }

        for canonical, column_name in VEHICLE_CLASS_COLUMNS.items():
            row[column_name] = int((group["vehicle_class"] == canonical).sum())

        for lane, column_name in LANE_COLUMNS.items():
            row[column_name] = int((group["lane_no"] == lane).sum())

        for mop_bucket, column_name in MOP_COLUMNS.items():
            row[column_name] = int(group["mop"].eq(mop_bucket).sum())

        row[TOTAL_TRANSACTION_COLUMN] = len(group)
        rows.append(row)

    return rows


def print_hourly_rows(rows: list[dict]) -> None:
    """Print final aggregated rows that would be inserted into the DB."""
    if not rows:
        print("  No hourly rows prepared.")
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

    data_columns = [
        "plaza_identifier",
        "plaza_name",
        "hour",
        "date",
        TOTAL_TRANSACTION_COLUMN,
    ]
    data_columns.extend(VEHICLE_CLASS_COLUMNS.values())
    data_columns.extend(LANE_COLUMNS.values())
    data_columns.extend(MOP_COLUMNS.values())

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
        fields=sql.SQL(", ").join(sql.Identifier(column) for column in data_columns),
    )

    values = [
        tuple(row[column] for column in data_columns)
        for row in rows_to_insert
    ]

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
        df = read_excel_file(file_path, required_fields=VOLUME_REQUIRED_FIELDS)
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

    hourly_rows = aggregate_hourly_rows(prepared)

    if dry_run:
        print("  DRY RUN — skipping DB insert.")
        print_hourly_rows(hourly_rows)
        return len(hourly_rows), False

    print("  Starting DB insertion...")
    inserted, skipped = upsert_rows(conn, table_name, hourly_rows)
    print(f"  Hourly rows inserted: {inserted}, skipped (already exists): {skipped}")
    return inserted, False


def process_folder(folder_path: str, dry_run: bool = DRY_RUN) -> None:
    require_plaza_settings()
    folder = Path(folder_path)
    if not folder.is_dir():
        raise FileNotFoundError(f"Input folder not found: {folder_path}")

    table_name = get_analytics_table_name()
    files = list_excel_files(folder)
    if not files:
        print(f"No Excel/CSV files found under: {folder} (including subfolders)")
        return

    print(f"Plaza identifier: {PLAZA_IDENTIFIER}")
    print(f"Plaza name: {PLAZA_NAME}")
    print(f"Target database: {get_analytics_db_connection_kwargs()['database']}")
    print(f"Target table: {table_name}")
    print(f"Files found: {len(files)}")

    run_log = create_run_log_file(ROOT_DIR, "module1")
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
            f"\nDry run complete. Total hourly rows prepared: {total_rows}. "
            f"Skipped files: {skipped_files}.",
        )
        print(f"\nDry run complete. Total hourly rows prepared: {total_rows}")
        print(f"Skipped files: {skipped_files}. Log: {run_log}")
        return

    conn = psycopg2.connect(**get_analytics_db_connection_kwargs())
    try:
        count_columns = [TOTAL_TRANSACTION_COLUMN]
        count_columns.extend(VEHICLE_CLASS_COLUMNS.values())
        count_columns.extend(LANE_COLUMNS.values())
        count_columns.extend(MOP_COLUMNS.values())
        ensure_analytics_table(conn, table_name, count_columns)
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
            f"\nCompleted. Total hourly rows inserted: {total_rows}. "
            f"Skipped files: {skipped_files}.",
        )
        print(f"\nCompleted. Total hourly rows inserted: {total_rows}")
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
