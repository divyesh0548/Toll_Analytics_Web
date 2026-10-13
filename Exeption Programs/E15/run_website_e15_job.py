"""
CLI entry used by the Website exception-job worker for E15.

Usage:
  python run_website_e15_job.py \\
    --from-folder <dir with From-plaza exempt files> \\
    --vrn-folder <dir with To-plaza VRN files> \\
    --plaza-identifier <uuid> \\
    [--entity-name <to-plaza entity>] \\
    [--output-file <from_to_combined.xlsx path>]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run E15 for a Website job")
    parser.add_argument("--from-folder", required=True)
    parser.add_argument("--vrn-folder", required=True)
    parser.add_argument("--plaza-identifier", required=True)
    parser.add_argument("--entity-name", default="")
    parser.add_argument("--output-file", default="")
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

    from_folder = Path(args.from_folder).expanduser().resolve()
    if not from_folder.is_dir():
        print(f"ERROR: From-plaza folder not found: {from_folder}")
        return 1

    vrn_folder = Path(args.vrn_folder).expanduser().resolve()
    if not vrn_folder.is_dir():
        print(f"ERROR: VRN folder not found: {vrn_folder}")
        return 1

    plaza_identifier = str(args.plaza_identifier).strip()
    if not plaza_identifier:
        print("ERROR: plaza_identifier is required")
        return 1

    e15_dir = Path(__file__).resolve().parent
    if str(e15_dir) not in sys.path:
        sys.path.insert(0, str(e15_dir))
    if str(e15_dir.parent) not in sys.path:
        sys.path.insert(0, str(e15_dir.parent))

    entity_name = str(args.entity_name or "").strip()
    if not entity_name:
        from common.plaza_entity_map import require_entity_name

        entity_name = require_entity_name(plaza_identifier)

    output_file = str(args.output_file or "").strip()
    if not output_file:
        output_file = str(
            (from_folder.parent / "output" / "from_to_combined.xlsx").resolve()
        )
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    os.environ["E15_FROM_PLAZA_FOLDER"] = str(from_folder)
    os.environ["E15_VRN_INPUT_FOLDER"] = str(vrn_folder)
    os.environ["E15_OUTPUT_FILE"] = output_file
    os.environ["E15_PLAZA_IDENTIFIER"] = plaza_identifier
    os.environ["E15_ENTITY_NAME"] = entity_name
    os.environ["E15_METRICS_DB_UPDATE"] = (
        "1"
        if str(args.update_metrics).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E15_UPLOAD_OUTPUT_TO_S3"] = (
        "1"
        if str(args.upload_output).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E15_DB_DRY_RUN"] = (
        "1"
        if str(args.dry_run).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    period_year = str(args.period_year or "").strip()
    period_month = str(args.period_month or "").strip()
    if period_year and period_month:
        os.environ["E15_PERIOD_YEAR"] = period_year
        os.environ["E15_PERIOD_MONTH"] = period_month
    else:
        os.environ.pop("E15_PERIOD_YEAR", None)
        os.environ.pop("E15_PERIOD_MONTH", None)

    print(
        f"Starting E15 from={from_folder} vrn={vrn_folder} "
        f"plaza_identifier={plaza_identifier} entity_name={entity_name!r} "
        f"output={output_file}"
    )
    import E15 as e15  # noqa: WPS433

    sys.argv = [sys.argv[0]]
    return int(e15.main())


if __name__ == "__main__":
    raise SystemExit(main())
