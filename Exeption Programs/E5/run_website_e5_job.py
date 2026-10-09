"""
CLI entry used by the Website exception-job worker for E05.

Usage:
  python run_website_e5_job.py \\
    --invalid-table <path> \\
    --plaza-identifier <uuid> \\
    [--ihmcl-file <path>] \\
    [--output-dir <dir>]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run E5 for a Website job")
    parser.add_argument("--invalid-table", required=True)
    parser.add_argument("--plaza-identifier", required=True)
    parser.add_argument("--entity-name", default="")
    parser.add_argument("--ihmcl-file", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--update-metrics", default="1")
    parser.add_argument("--upload-output", default="1")
    parser.add_argument("--dry-run", default="0")
    args = parser.parse_args()

    invalid_table = Path(args.invalid_table).expanduser().resolve()
    if not invalid_table.is_file():
        print(f"ERROR: invalid table not found: {invalid_table}")
        return 1

    plaza_identifier = str(args.plaza_identifier).strip()
    if not plaza_identifier:
        print("ERROR: plaza_identifier is required")
        return 1

    e5_dir = Path(__file__).resolve().parent
    if str(e5_dir) not in sys.path:
        sys.path.insert(0, str(e5_dir))
    if str(e5_dir.parent) not in sys.path:
        sys.path.insert(0, str(e5_dir.parent))

    entity_name = str(args.entity_name or "").strip()
    if not entity_name:
        from common.plaza_entity_map import require_entity_name

        entity_name = require_entity_name(plaza_identifier)

    output_dir = str(args.output_dir or "").strip()
    if not output_dir:
        output_dir = str((invalid_table.parent.parent / "output").resolve())
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    os.environ["E5_INPUT_FILE"] = str(invalid_table)
    os.environ["E5_PLAZA_IDENTIFIER"] = plaza_identifier
    os.environ["E5_ENTITY_NAME"] = entity_name
    os.environ["E5_OUTPUT_DIR"] = output_dir
    os.environ["E5_METRICS_DB_UPDATE"] = (
        "1"
        if str(args.update_metrics).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E5_UPLOAD_OUTPUT_TO_S3"] = (
        "1"
        if str(args.upload_output).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )
    os.environ["E5_DB_DRY_RUN"] = (
        "1"
        if str(args.dry_run).strip().lower() in {"1", "true", "yes", "on"}
        else "0"
    )

    ihmcl = str(args.ihmcl_file or "").strip()
    if ihmcl:
        ihmcl_path = Path(ihmcl).expanduser().resolve()
        if not ihmcl_path.is_file():
            print(f"ERROR: IHMCL file not found: {ihmcl_path}")
            return 1
        os.environ["E5_IHMCL_INPUT_FILE"] = str(ihmcl_path)
    else:
        os.environ.pop("E5_IHMCL_INPUT_FILE", None)

    print(
        f"Starting E5 invalid_table={invalid_table} "
        f"plaza_identifier={plaza_identifier} entity_name={entity_name!r} "
        f"ihmcl={'yes' if ihmcl else 'scrape'}"
    )
    import Main_E5 as e5  # noqa: WPS433

    sys.argv = [sys.argv[0]]
    return int(e5.main())


if __name__ == "__main__":
    raise SystemExit(main())
