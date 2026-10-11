"""
CLI entry used by the Website exception-job worker for E06.

Usage:
  python run_website_e6_job.py \\
    --etc-folder <dir> \\
    --vrn-folder <dir> \\
    --plaza-identifier <uuid> \\
    [--permit-folder <dir>] \\
    [--output-file <path>]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run E6 for a Website job")
    parser.add_argument("--etc-folder", required=True)
    parser.add_argument("--vrn-folder", required=True)
    parser.add_argument("--plaza-identifier", required=True)
    parser.add_argument("--entity-name", default="")
    parser.add_argument("--permit-folder", default="")
    parser.add_argument("--output-file", default="")
    parser.add_argument("--update-metrics", default="1")
    parser.add_argument("--upload-output", default="1")
    parser.add_argument("--dry-run", default="0")
    args = parser.parse_args()

    etc_folder = Path(args.etc_folder).expanduser().resolve()
    if not etc_folder.is_dir():
        print(f"ERROR: ETC folder not found: {etc_folder}")
        return 1

    vrn_folder = Path(args.vrn_folder).expanduser().resolve()
    if not vrn_folder.is_dir():
        print(f"ERROR: VRN folder not found: {vrn_folder}")
        return 1

    plaza_identifier = str(args.plaza_identifier).strip()
    if not plaza_identifier:
        print("ERROR: plaza_identifier is required")
        return 1

    e6_dir = Path(__file__).resolve().parent
    if str(e6_dir) not in sys.path:
        sys.path.insert(0, str(e6_dir))
    if str(e6_dir.parent) not in sys.path:
        sys.path.insert(0, str(e6_dir.parent))

    entity_name = str(args.entity_name or "").strip()
    if not entity_name:
        from common.plaza_entity_map import require_entity_name

        entity_name = require_entity_name(plaza_identifier)

    output_file = str(args.output_file or "").strip()
    if not output_file:
        output_file = str(
            (etc_folder.parent / "output" / "etc_enriched.xlsx").resolve()
        )
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    os.environ["E6_ETC_INPUT_FOLDER"] = str(etc_folder)
    os.environ["E6_VRN_INPUT_FOLDER"] = str(vrn_folder)
    os.environ["E6_OUTPUT_FILE"] = output_file
    os.environ["E6_PLAZA_IDENTIFIER"] = plaza_identifier
    os.environ["E6_ENTITY_NAME"] = entity_name
    os.environ["E6_METRICS_DB_UPDATE"] = (
        "1"
        if str(args.update_metrics).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E6_UPLOAD_OUTPUT_TO_S3"] = (
        "1"
        if str(args.upload_output).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E6_DB_DRY_RUN"] = (
        "1"
        if str(args.dry_run).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )

    permit = str(args.permit_folder or "").strip()
    if permit:
        permit_path = Path(permit).expanduser().resolve()
        if not permit_path.is_dir():
            print(f"ERROR: permit folder not found: {permit_path}")
            return 1
        os.environ["E6_PERMIT_FOLDER"] = str(permit_path)
        permit_mode = "upload"
    else:
        # Empty folder → E6_main scrapes Parivahan.
        os.environ["E6_PERMIT_FOLDER"] = ""
        permit_mode = "scrape"

    print(
        f"Starting E6 etc={etc_folder} vrn={vrn_folder} "
        f"plaza_identifier={plaza_identifier} entity_name={entity_name!r} "
        f"permit={permit_mode} output={output_file}"
    )
    import E6_main as e6  # noqa: WPS433

    sys.argv = [sys.argv[0]]
    return int(e6.main())


if __name__ == "__main__":
    raise SystemExit(main())
