"""
CLI entry used by the Website analytics-job worker.

Usage:
  python run_website_analytics_job.py \\
    --plaza-identifier <uuid> \\
    --plaza-name <name> \\
    [--vrn-folder <dir>] \\
    [--etc-folder <dir>] \\
    [--start-date-limit YYYY-MM-DD]

At least one of --vrn-folder / --etc-folder is required.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run plaza VRN/ETC ETL for a Website job")
    parser.add_argument("--plaza-identifier", required=True)
    parser.add_argument("--plaza-name", required=True)
    parser.add_argument("--vrn-folder", default="")
    parser.add_argument("--etc-folder", default="")
    parser.add_argument("--start-date-limit", default="2000-01-01")
    parser.add_argument("--dry-run", default="0")
    args = parser.parse_args()

    plaza_identifier = str(args.plaza_identifier).strip()
    plaza_name = str(args.plaza_name).strip()
    if not plaza_identifier:
        print("ERROR: plaza_identifier is required")
        return 1
    if not plaza_name:
        print("ERROR: plaza_name is required")
        return 1

    vrn_path: Path | None = None
    vrn_folder = str(args.vrn_folder or "").strip()
    if vrn_folder:
        vrn_path = Path(vrn_folder).expanduser().resolve()
        if not vrn_path.is_dir():
            print(f"ERROR: VRN folder not found: {vrn_path}")
            return 1

    etc_path: Path | None = None
    etc_folder = str(args.etc_folder or "").strip()
    if etc_folder:
        etc_path = Path(etc_folder).expanduser().resolve()
        if not etc_path.is_dir():
            print(f"ERROR: ETC folder not found: {etc_path}")
            return 1

    if vrn_path is None and etc_path is None:
        print("ERROR: provide at least one of --vrn-folder or --etc-folder")
        return 1

    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    os.environ["PLAZA_ETL_PLAZA_IDENTIFIER"] = plaza_identifier
    os.environ["PLAZA_ETL_PLAZA_NAME"] = plaza_name
    os.environ["PLAZA_ETL_VRN_FOLDER"] = str(vrn_path) if vrn_path else ""
    os.environ["PLAZA_ETL_ETC_FOLDER"] = str(etc_path) if etc_path else ""
    os.environ["PLAZA_ETL_START_DATE_LIMIT"] = str(args.start_date_limit or "2000-01-01").strip()

    dry_run = str(args.dry_run).strip().lower() in {"1", "true", "yes", "on"}

    print(
        f"Starting analytics ETL plaza={plaza_name!r} ({plaza_identifier}) "
        f"vrn={vrn_path or '(none)'} etc={etc_path or '(none)'} "
        f"start_date_limit={os.environ['PLAZA_ETL_START_DATE_LIMIT']} dry_run={dry_run}"
    )

    import run_plaza_etl as etl  # noqa: WPS433

    etl.process_vrn_and_optional_etc(
        str(vrn_path) if vrn_path else "",
        etc_folder=str(etc_path) if etc_path else "",
        dry_run=dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
