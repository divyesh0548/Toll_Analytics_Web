"""
CLI entry used by the Website exception-job worker for E11.

Usage:
  python run_website_e11_job.py \\
    --vrn-folder <dir with uploaded VRN files> \\
    --plaza-identifier <uuid> \\
    --entity-name <submissions entity> \\
    [--output-dir <dir>]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run E11 for a Website job")
    parser.add_argument("--vrn-folder", required=True)
    parser.add_argument("--plaza-identifier", required=True)
    parser.add_argument("--entity-name", required=True)
    parser.add_argument(
        "--output-dir",
        default="",
        help="Output directory (default: <vrn-folder>/../output)",
    )
    parser.add_argument("--update-metrics", default="1")
    parser.add_argument("--upload-output", default="1")
    parser.add_argument("--dry-run", default="0")
    parser.add_argument(
        "--period-year",
        default="",
        help="Pipeline batch year — roll metrics into this month",
    )
    parser.add_argument(
        "--period-month",
        default="",
        help="Pipeline batch month (1-12) — roll metrics into this month",
    )
    args = parser.parse_args()

    vrn_folder = Path(args.vrn_folder).expanduser().resolve()
    if not vrn_folder.is_dir():
        print(f"ERROR: VRN folder not found: {vrn_folder}")
        return 1

    plaza_identifier = str(args.plaza_identifier).strip()
    entity_name = str(args.entity_name).strip()
    if not plaza_identifier:
        print("ERROR: plaza_identifier is required")
        return 1
    if not entity_name:
        print("ERROR: entity_name is required")
        return 1

    output_dir = str(args.output_dir or "").strip()
    if not output_dir:
        output_dir = str((vrn_folder.parent / "output").resolve())
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    os.environ["E11_VRN_INPUT_FOLDER"] = str(vrn_folder)
    os.environ["E11_OUTPUT_DIR"] = output_dir
    os.environ["E11_PLAZA_IDENTIFIER"] = plaza_identifier
    os.environ["E11_ENTITY_NAME"] = entity_name
    os.environ["E11_NONINTERACTIVE"] = "1"
    os.environ["E11_METRICS_DB_UPDATE"] = (
        "1"
        if str(args.update_metrics).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E11_UPLOAD_OUTPUT_TO_S3"] = (
        "1"
        if str(args.upload_output).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E11_DB_DRY_RUN"] = (
        "1"
        if str(args.dry_run).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    period_year = str(args.period_year or "").strip()
    period_month = str(args.period_month or "").strip()
    if period_year and period_month:
        os.environ["E11_PERIOD_YEAR"] = period_year
        os.environ["E11_PERIOD_MONTH"] = period_month
    else:
        os.environ.pop("E11_PERIOD_YEAR", None)
        os.environ.pop("E11_PERIOD_MONTH", None)

    e11_dir = Path(__file__).resolve().parent
    if str(e11_dir) not in sys.path:
        sys.path.insert(0, str(e11_dir))
    if str(e11_dir.parent) not in sys.path:
        sys.path.insert(0, str(e11_dir.parent))

    print(
        f"Starting E11 vrn_folder={vrn_folder} "
        f"plaza_identifier={plaza_identifier} entity={entity_name} "
        f"output_dir={output_dir}"
    )
    import Main_E11 as e11  # noqa: WPS433

    sys.argv = [sys.argv[0]]
    return int(e11.main())


if __name__ == "__main__":
    raise SystemExit(main())
