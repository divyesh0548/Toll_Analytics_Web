"""
CLI entry used by the Website exception-job worker for E10.

Usage:
  python run_website_e10_job.py \\
    --vrn-folder <dir> \\
    --etc-folder <dir> \\
    --plaza-identifier <uuid> \\
    [--entity-name <name>] \\
    [--output-file <merged csv path>]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run E10 for a Website job")
    parser.add_argument("--vrn-folder", required=True)
    parser.add_argument("--etc-folder", required=True)
    parser.add_argument("--plaza-identifier", required=True)
    parser.add_argument("--entity-name", default="")
    parser.add_argument("--output-file", default="")
    parser.add_argument("--update-metrics", default="1")
    parser.add_argument("--upload-output", default="1")
    parser.add_argument("--dry-run", default="0")
    args = parser.parse_args()

    vrn_folder = Path(args.vrn_folder).expanduser().resolve()
    if not vrn_folder.is_dir():
        print(f"ERROR: VRN folder not found: {vrn_folder}")
        return 1

    etc_folder = Path(args.etc_folder).expanduser().resolve()
    if not etc_folder.is_dir():
        print(f"ERROR: ETC folder not found: {etc_folder}")
        return 1

    plaza_identifier = str(args.plaza_identifier).strip()
    if not plaza_identifier:
        print("ERROR: plaza_identifier is required")
        return 1

    e10_dir = Path(__file__).resolve().parent
    if str(e10_dir) not in sys.path:
        sys.path.insert(0, str(e10_dir))
    if str(e10_dir.parent) not in sys.path:
        sys.path.insert(0, str(e10_dir.parent))

    entity_name = str(args.entity_name or "").strip()
    if not entity_name:
        from common.plaza_entity_map import require_entity_name

        entity_name = require_entity_name(plaza_identifier)

    output_file = str(args.output_file or "").strip()
    if not output_file:
        output_file = str(
            (vrn_folder.parent / "output" / "e10_vrn_etc_merged.csv").resolve()
        )
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    os.environ["E10_VRN_INPUT_FOLDER"] = str(vrn_folder)
    os.environ["E10_ETC_INPUT_FOLDER"] = str(etc_folder)
    os.environ["E10_OUTPUT_FILE"] = output_file
    os.environ["E10_PLAZA_IDENTIFIER"] = plaza_identifier
    os.environ["E10_ENTITY_NAME"] = entity_name
    os.environ["E10_METRICS_DB_UPDATE"] = (
        "1"
        if str(args.update_metrics).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E10_UPLOAD_OUTPUT_TO_S3"] = (
        "1"
        if str(args.upload_output).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E10_DB_DRY_RUN"] = (
        "1"
        if str(args.dry_run).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )

    print(
        f"Starting E10 vrn={vrn_folder} etc={etc_folder} "
        f"plaza_identifier={plaza_identifier} entity_name={entity_name!r} "
        f"output={output_file}"
    )
    import Main_E10 as e10  # noqa: WPS433

    sys.argv = [sys.argv[0]]
    return int(e10.main())


if __name__ == "__main__":
    raise SystemExit(main())
