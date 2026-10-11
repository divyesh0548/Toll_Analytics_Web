"""
CLI entry used by the Website exception-job worker for E09.

Usage:
  python run_website_e9_job.py \\
    --etc-folder <dir with uploaded ETC files> \\
    --plaza-identifier <uuid> \\
    [--output-file <csv path>]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run E9 for a Website job")
    parser.add_argument("--etc-folder", required=True)
    parser.add_argument("--plaza-identifier", required=True)
    parser.add_argument(
        "--output-file",
        default="",
        help="Unsettled CSV path (default: <etc-folder>/../output/e9_unsettled.csv)",
    )
    parser.add_argument("--update-metrics", default="1")
    parser.add_argument("--upload-output", default="1")
    parser.add_argument("--dry-run", default="0")
    args = parser.parse_args()

    etc_folder = Path(args.etc_folder).expanduser().resolve()
    if not etc_folder.is_dir():
        print(f"ERROR: ETC folder not found: {etc_folder}")
        return 1

    plaza_identifier = str(args.plaza_identifier).strip()
    if not plaza_identifier:
        print("ERROR: plaza_identifier is required")
        return 1

    output_file = str(args.output_file or "").strip()
    if not output_file:
        output_file = str(
            (etc_folder.parent / "output" / "e9_unsettled.csv").resolve()
        )
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    os.environ["E9_ETC_INPUT_FOLDER"] = str(etc_folder)
    os.environ["E9_OUTPUT_FILE"] = output_file
    os.environ["E9_PLAZA_IDENTIFIER"] = plaza_identifier
    os.environ["E9_METRICS_DB_UPDATE"] = (
        "1"
        if str(args.update_metrics).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E9_UPLOAD_OUTPUT_TO_S3"] = (
        "1"
        if str(args.upload_output).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E9_DB_DRY_RUN"] = (
        "1"
        if str(args.dry_run).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )

    e9_dir = Path(__file__).resolve().parent
    if str(e9_dir) not in sys.path:
        sys.path.insert(0, str(e9_dir))
    if str(e9_dir.parent) not in sys.path:
        sys.path.insert(0, str(e9_dir.parent))

    print(
        f"Starting E9 etc_folder={etc_folder} "
        f"plaza_identifier={plaza_identifier} output={output_file}"
    )
    import Main_E9 as e9  # noqa: WPS433

    sys.argv = [sys.argv[0]]
    return int(e9.main())


if __name__ == "__main__":
    raise SystemExit(main())
