"""
Download VRN files from S3 URLs stored in the submissions table.

Filters by plaza (entity_name) and date range, then saves files to OUTPUT_FOLDER.

Configure PLAZA_NAME, FROM_DATE, TO_DATE, and OUTPUT_FOLDER below, then run:
    python VRN_downloaded.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import psycopg2
import requests

# submissions DB credentials live in the NHIT processing project
NHIT_DIR = Path(__file__).resolve().parent.parent / "NHIT_dashboard_processing"
sys.path.insert(0, str(NHIT_DIR))

from db_config import get_db_connection_kwargs, load_env_file, parse_env_date

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PLAZA_NAME = "bassi"
FROM_DATE = "2025-11-20"  # YYYY-MM-DD
TO_DATE = "2026-08-31"    # YYYY-MM-DD
OUTPUT_FOLDER = r"C:\Divyesh\Toll Analytics Dashboard\Bassi VRNs"

DOWNLOAD_TIMEOUT_SECONDS = 120
SKIP_EXISTING = True

TABLE_NAME = "submissions"


def validate_dates(from_date: str, to_date: str) -> tuple[str, str]:
    from_dt = parse_env_date(from_date)
    to_dt = parse_env_date(to_date)
    if to_dt < from_dt:
        raise ValueError("TO_DATE must be on or after FROM_DATE.")
    return from_dt.strftime("%Y-%m-%d"), to_dt.strftime("%Y-%m-%d")


def fetch_vrn_records(plaza_name: str, from_date: str, to_date: str) -> list[dict]:
    query = f"""
        SELECT id, entity_name, date, shift, vrn_file_url
        FROM {TABLE_NAME}
        WHERE entity_name = %s
          AND date >= %s
          AND date <= %s
          AND vrn_file_url IS NOT NULL
          AND TRIM(vrn_file_url) <> ''
        ORDER BY date, shift, id
    """

    with psycopg2.connect(**get_db_connection_kwargs()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (plaza_name, from_date, to_date))
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()

    return [dict(zip(columns, row)) for row in rows]


def filename_from_url(url: str, record_id: int) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if name:
        return name
    return f"vrn_{record_id}.xlsx"


def build_local_path(
    output_folder: Path,
    entity_name: str,
    record_date,
    shift,
    filename: str,
    ) -> Path:
    date_str = record_date.strftime("%Y-%m-%d") if hasattr(record_date, "strftime") else str(record_date)
    shift_part = str(shift).strip() if shift not in (None, "") else "unknown_shift"
    shift_part = shift_part.replace("/", "-").replace("\\", "-").replace(":", "-")
    return output_folder / entity_name / date_str / shift_part / filename


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()
    destination.write_bytes(response.content)


def download_vrn_files(
    plaza_name: str,
    from_date: str,
    to_date: str,
    output_folder: str | Path,
    skip_existing: bool = SKIP_EXISTING,
    ) -> dict[str, int]:
    load_env_file()
    from_date, to_date = validate_dates(from_date, to_date)
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    records = fetch_vrn_records(plaza_name, from_date, to_date)
    stats = {"found": len(records), "downloaded": 0, "skipped": 0, "failed": 0}

    print(f"Plaza: {plaza_name}")
    print(f"Date range: {from_date} to {to_date}")
    print(f"Output folder: {output_path.resolve()}")
    print(f"Records with VRN URL: {len(records)}\n")

    if not records:
        print("No VRN files found for the given filters.")
        return stats

    for index, record in enumerate(records, start=1):
        record_id = record["id"]
        url = record["vrn_file_url"].strip()
        filename = filename_from_url(url, record_id)
        local_path = build_local_path(
            output_path,
            record["entity_name"],
            record["date"],
            record.get("shift"),
            filename,
        )

        prefix = f"[{index}/{len(records)}] id={record_id} date={record['date']} shift={record.get('shift')}"

        if skip_existing and local_path.exists():
            print(f"{prefix} SKIP (exists): {local_path}")
            stats["skipped"] += 1
            continue

        try:
            print(f"{prefix} DOWNLOAD -> {local_path}")
            download_file(url, local_path)
            stats["downloaded"] += 1
        except requests.RequestException as exc:
            print(f"{prefix} FAILED: {exc}")
            stats["failed"] += 1

    print("\nSummary")
    print(f"  Found:      {stats['found']}")
    print(f"  Downloaded: {stats['downloaded']}")
    print(f"  Skipped:    {stats['skipped']}")
    print(f"  Failed:     {stats['failed']}")

    return stats


def main() -> None:
    try:
        download_vrn_files(
            plaza_name=PLAZA_NAME,
            from_date=FROM_DATE,
            to_date=TO_DATE,
            output_folder=OUTPUT_FOLDER,
            skip_existing=SKIP_EXISTING,
        )
    except (RuntimeError, ValueError, psycopg2.Error) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
