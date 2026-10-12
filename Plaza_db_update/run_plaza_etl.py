"""
Main plaza ETL runner.

Parses each VRN Excel/CSV once, then writes all hourly insights:
  - mop_distribution_per_class
  - class_distribution_per_lane
  - mop_distribution_per_lane
  - gap_distribution_per_lane

Optional: when PLAZA_ETL_ETC_FOLDER / ETC_INPUT_FOLDER is set, also runs
module4 local ETC revenue upsert after VRN.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from config.db import ensure_all_analytics_tables, get_analytics_db_connection_kwargs
from config.settings import (
    ETC_INPUT_FOLDER,
    INPUT_FOLDER,
    PLAZA_IDENTIFIER,
    PLAZA_NAME,
    START_DATE_LIMIT,
    apply_website_env_overrides,
)
from excel_common import (
    UnmappedValueError,
    append_run_log,
    create_run_log_file,
    is_skippable_excel_read_error,
    list_excel_files,
    read_excel_file,
    resolve_datetime_columns,
)
from insights import (
    class_distribution_per_lane,
    gap_distribution_per_lane,
    mop_distribution_per_class,
    mop_distribution_per_lane,
)
from insights.common import (
    REQUIRED_FIELDS,
    prepare_dataframe,
    print_validation_errors,
    require_plaza_settings,
    validate_dataframe,
)

DRY_RUN = False


def _refresh_settings() -> tuple[str, str, str, str, str]:
    """Apply env overrides and return (plaza_id, plaza_name, vrn, etc, start)."""
    apply_website_env_overrides()
    from config import settings as s

    return (
        s.PLAZA_IDENTIFIER,
        s.PLAZA_NAME,
        s.INPUT_FOLDER,
        s.ETC_INPUT_FOLDER,
        s.START_DATE_LIMIT,
    )


def process_file(file_path: Path, conn=None, *, dry_run: bool = False, run_log: Path | None = None) -> bool:
    """
    Parse one file and write all insight tables.
    Returns True if the file was skipped (header / unreadable workbook), False otherwise.
    """
    print(f"\nProcessing file: {file_path}")
    try:
        df = read_excel_file(file_path, required_fields=REQUIRED_FIELDS)
    except Exception as exc:
        if is_skippable_excel_read_error(exc):
            message = f"[SKIP] {file_path} — {exc}"
            print(f"  {message}")
            if run_log is not None:
                append_run_log(run_log, message)
            return True
        print(f"\n  File preparation failed: {exc}")
        raise UnmappedValueError(
            f"File '{file_path.name}' could not be prepared. No rows were inserted."
        ) from exc

    print(f"  Rows read after header detection: {len(df)}")
    try:
        datetime_resolution = resolve_datetime_columns(df)
    except ValueError as exc:
        print(f"\n  Datetime resolution failed: {exc}")
        raise UnmappedValueError(
            f"File '{file_path.name}' datetime columns could not be resolved. "
            "No rows were inserted."
        ) from exc
    print(f"  Detected datetime: {datetime_resolution.label}")

    errors = validate_dataframe(df, file_path.name, datetime_resolution)
    if errors:
        print_validation_errors(errors)
        raise UnmappedValueError(
            f"File '{file_path.name}' failed validation. No rows were inserted."
        )

    print("  Validation passed.")
    prepared = prepare_dataframe(df, datetime_resolution)
    _, _, _, _, start_limit = _refresh_settings()
    if prepared.empty:
        print(f"  No rows on or after {start_limit}. Skipping file.")
        return False

    print(f"  Prepared rows for aggregation: {len(prepared)}")

    class_mop_rows = mop_distribution_per_class.aggregate(prepared)
    class_lane_rows = class_distribution_per_lane.aggregate(prepared)
    mop_lane_rows = mop_distribution_per_lane.aggregate(prepared)
    gap_rows = gap_distribution_per_lane.aggregate(prepared)

    print(
        "  Aggregated: "
        f"class×mop={len(class_mop_rows)}, "
        f"class×lane={len(class_lane_rows)}, "
        f"mop×lane={len(mop_lane_rows)}, "
        f"gap={len(gap_rows)}"
    )

    mop_distribution_per_class.write(conn, class_mop_rows, dry_run=dry_run)
    class_distribution_per_lane.write(conn, class_lane_rows, dry_run=dry_run)
    mop_distribution_per_lane.write(conn, mop_lane_rows, dry_run=dry_run)
    gap_distribution_per_lane.write(conn, gap_rows, dry_run=dry_run)
    return False


def process_folder(folder_path: str, *, dry_run: bool = DRY_RUN) -> None:
    require_plaza_settings()
    plaza_id, plaza_name, _, _, _ = _refresh_settings()
    folder = Path(folder_path)
    if not folder.is_dir():
        raise FileNotFoundError(f"Input folder not found: {folder_path}")

    files = list_excel_files(folder)
    if not files:
        print(f"No Excel/CSV files found under: {folder}")
        return

    print(f"Plaza identifier: {plaza_id}")
    print(f"Plaza name: {plaza_name}")
    print(f"Input folder: {folder}")
    print(f"Files found: {len(files)}")
    if dry_run:
        print("DRY RUN enabled — no DB writes.")

    run_log = create_run_log_file(ROOT_DIR, "run_plaza_etl")
    print(f"Run log: {run_log}")
    append_run_log(
        run_log,
        f"Plaza identifier: {plaza_id}\nPlaza: {plaza_name}\n"
        f"Input folder: {folder}\nFiles found: {len(files)}\nDry run: {dry_run}",
    )

    skipped_files = 0
    if dry_run:
        for file_path in files:
            try:
                if process_file(file_path, dry_run=True, run_log=run_log):
                    skipped_files += 1
            except UnmappedValueError:
                append_run_log(run_log, "Execution stopped due to validation failure.")
                print("\nExecution stopped. Fix the abnormal values above and rerun.")
                print(f"See log: {run_log}")
                sys.exit(1)
        append_run_log(
            run_log,
            f"\nDry run complete. Skipped files: {skipped_files}.",
        )
        print(f"\nDry run complete. Skipped files: {skipped_files}. Log: {run_log}")
        return

    conn = psycopg2.connect(**get_analytics_db_connection_kwargs())
    try:
        print(f"Target database: {get_analytics_db_connection_kwargs()['database']}")
        ensure_all_analytics_tables(conn)
        for file_path in files:
            try:
                if process_file(file_path, conn=conn, dry_run=False, run_log=run_log):
                    skipped_files += 1
            except UnmappedValueError:
                append_run_log(run_log, "Execution stopped due to validation failure.")
                print("\nExecution stopped. Fix the abnormal values above and rerun.")
                print(f"See log: {run_log}")
                sys.exit(1)
    finally:
        conn.close()

    append_run_log(run_log, f"\nCompleted. Skipped files: {skipped_files}.")
    print(f"\nCompleted. Skipped files: {skipped_files}. Log: {run_log}")


def process_vrn_and_optional_etc(
    vrn_folder: str = "",
    *,
    etc_folder: str = "",
    dry_run: bool = DRY_RUN,
) -> None:
    """VRN insights and/or local ETC revenue (Website analytics jobs).

    At least one of vrn_folder / etc_folder should be set.
    """
    vrn = str(vrn_folder or "").strip()
    etc = str(etc_folder or "").strip()
    if not etc:
        _, _, _, etc_from_settings, _ = _refresh_settings()
        etc = str(etc_from_settings or "").strip()

    if vrn:
        process_folder(vrn, dry_run=dry_run)
    else:
        print("No VRN folder set — skipping VRN insight tables.")

    if etc:
        import module4  # noqa: WPS433

        module4.run_local_etc_folder(etc, dry_run=dry_run)
    else:
        print("No ETC folder set — skipping module4 revenue load.")

    if not vrn and not etc:
        raise RuntimeError("Nothing to process: provide a VRN folder and/or an ETC folder.")


if __name__ == "__main__":
    apply_website_env_overrides()
    plaza_id, plaza_name, vrn_folder, etc_folder, _ = _refresh_settings()
    folder_path = sys.argv[1] if len(sys.argv) > 1 else vrn_folder or INPUT_FOLDER
    if etc_folder:
        process_vrn_and_optional_etc(folder_path, etc_folder=etc_folder, dry_run=DRY_RUN)
    else:
        process_folder(folder_path, dry_run=DRY_RUN)
