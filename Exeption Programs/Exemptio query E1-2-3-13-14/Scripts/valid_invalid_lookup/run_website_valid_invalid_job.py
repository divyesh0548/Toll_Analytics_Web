"""
CLI entry used by the Website exception-job worker for Valid/Invalid Lookup (E05 prep).

Uploads invalid_table.csv to S3 as a non-final staging file (exception_type_id=5).
Does NOT update audit_exception_metrics.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Valid/Invalid Lookup for a Website job")
    parser.add_argument("--lifecycle-file", required=True)
    parser.add_argument("--plaza-identifier", required=True)
    parser.add_argument("--entity-name", required=True, help="plaza_rates key from plaza_entity_map")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--upload-staging", default="1")
    args = parser.parse_args()

    lifecycle = Path(args.lifecycle_file).expanduser().resolve()
    if not lifecycle.is_file():
        print(f"ERROR: lifecycle file not found: {lifecycle}")
        return 1

    plaza_identifier = str(args.plaza_identifier).strip()
    entity_name = str(args.entity_name).strip()
    if not plaza_identifier or not entity_name:
        print("ERROR: plaza_identifier and entity_name are required")
        return 1

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    os.environ["VALID_INVALID_LIFECYCLE_PATH"] = str(lifecycle)
    os.environ["VALID_INVALID_PLAZA_NAME"] = entity_name
    os.environ["VALID_INVALID_OUTPUT_DIR"] = str(output_dir)

    here = Path(__file__).resolve().parent
    scripts_dir = here.parent
    portal_root = scripts_dir.parent
    exception_root = portal_root.parent
    e4_dir = exception_root / "E4"
    for path in (e4_dir, portal_root, scripts_dir, here):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    print(
        f"Starting Valid/Invalid Lookup lifecycle={lifecycle} "
        f"entity_name={entity_name!r} plaza_identifier={plaza_identifier}"
    )

    import Valid_Invalid_Full_Process as vil  # noqa: WPS433

    try:
        vil.main()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        return 1

    invalid_path = output_dir / "invalid_table.csv"
    if not invalid_path.is_file():
        print(f"ERROR: invalid_table.csv was not produced at {invalid_path}")
        return 1

    upload = str(args.upload_staging).strip().lower() in {"1", "true", "yes", "on"}
    if not upload:
        print("UPLOAD staging skipped.")
        return 0

    if str(exception_root) not in sys.path:
        sys.path.insert(0, str(exception_root))
    from common.s3_output_upload import (  # noqa: E402
        month_label_from_periods,
        upload_exception_output,
    )

    # Month label from file mtime day is weak; use "staging" + stamp in file name.
    # Prefer detecting dates from the invalid table when possible.
    month_label = "staging"
    try:
        import pandas as pd

        sample = pd.read_csv(invalid_path, nrows=5000, low_memory=False)
        date_col = None
        for candidate in (
            "Reader Read Time",
            "Date & Time",
            "Settlement Date",
            "Tag Read Date Time",
        ):
            if candidate in sample.columns:
                date_col = candidate
                break
        if date_col:
            parsed = pd.to_datetime(sample[date_col], errors="coerce")
            periods = {
                (int(ts.year), int(ts.month))
                for ts in parsed.dropna()
            }
            if periods:
                month_label = month_label_from_periods(sorted(periods))
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: could not derive month_label from invalid table ({exc})")

    plaza_safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in entity_name)
    print(
        f"Uploading staging invalid_table for plaza={entity_name!r} "
        f"month_label={month_label!r} (is_final_output=False)…"
    )
    upload_exception_output(
        invalid_path,
        plaza_identifier,
        exception_type_id=5,
        month_label=month_label,
        is_final_output=False,
        name_stem=f"invalid_table_{plaza_safe}_{datetime.now().strftime('%Y%m%d')}",
    )
    print("Staging invalid table uploaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
