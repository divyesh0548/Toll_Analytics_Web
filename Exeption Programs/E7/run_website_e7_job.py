"""
CLI entry used by the Website exception-job worker for E07.

Usage:
  python run_website_e7_job.py \\
    --pass-folder <dir with uploaded pass files> \\
    --plaza-identifier <uuid> \\
    [--output-file <csv path>]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run E7 for a Website job")
    parser.add_argument("--pass-folder", required=True)
    parser.add_argument("--plaza-identifier", required=True)
    parser.add_argument(
        "--output-file",
        default="",
        help="Loss CSV path (default: <pass-folder>/../output/e7_vc4_loss.csv)",
    )
    parser.add_argument("--update-metrics", default="1")
    parser.add_argument("--upload-output", default="1")
    parser.add_argument("--dry-run", default="0")
    args = parser.parse_args()

    pass_folder = Path(args.pass_folder).expanduser().resolve()
    if not pass_folder.is_dir():
        print(f"ERROR: pass folder not found: {pass_folder}")
        return 1

    plaza_identifier = str(args.plaza_identifier).strip()
    if not plaza_identifier:
        print("ERROR: plaza_identifier is required")
        return 1

    output_file = str(args.output_file or "").strip()
    if not output_file:
        output_file = str(
            (pass_folder.parent / "output" / "e7_vc4_loss.csv").resolve()
        )
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    os.environ["E7_PASS_INPUT_FOLDER"] = str(pass_folder)
    os.environ["E7_OUTPUT_FILE"] = output_file
    os.environ["E7_PLAZA_IDENTIFIER"] = plaza_identifier
    os.environ["E7_METRICS_DB_UPDATE"] = (
        "1"
        if str(args.update_metrics).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E7_UPLOAD_OUTPUT_TO_S3"] = (
        "1"
        if str(args.upload_output).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E7_DB_DRY_RUN"] = (
        "1"
        if str(args.dry_run).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )

    e7_dir = Path(__file__).resolve().parent
    if str(e7_dir) not in sys.path:
        sys.path.insert(0, str(e7_dir))
    if str(e7_dir.parent) not in sys.path:
        sys.path.insert(0, str(e7_dir.parent))

    print(
        f"Starting E7 pass_folder={pass_folder} "
        f"plaza_identifier={plaza_identifier} output={output_file}"
    )
    import Main_E7 as e7  # noqa: WPS433

    sys.argv = [sys.argv[0]]
    return int(e7.main())


if __name__ == "__main__":
    raise SystemExit(main())
