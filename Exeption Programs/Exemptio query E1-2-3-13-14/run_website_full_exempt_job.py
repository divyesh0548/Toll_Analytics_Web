"""
CLI entry used by the Website exception-job worker.

Usage:
  python run_website_full_exempt_job.py \\
    --process-name web_abc123 \\
    --plaza-key BASSI \\
    --plaza-identifier <uuid> \\
    [--update-metrics 1]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Full Exempt Pipeline for a Website job")
    parser.add_argument("--process-name", required=True)
    parser.add_argument("--plaza-key", required=True, help="codes_dump plaza key, e.g. BASSI")
    parser.add_argument("--plaza-identifier", required=True)
    parser.add_argument(
        "--update-metrics",
        default="1",
        help="1/true to sync E01/E02/E03/E13/E14 metrics after annexure",
    )
    args = parser.parse_args()

    portal_root = Path(__file__).resolve().parent
    if str(portal_root) not in sys.path:
        sys.path.insert(0, str(portal_root))

    # Import portal helpers (creates File_Process dirs on import — expected).
    import app as portal  # noqa: WPS433

    process_name = str(args.process_name).strip()
    plaza_key = str(args.plaza_key).strip().upper()
    plaza_identifier = str(args.plaza_identifier).strip()
    update_metrics = str(args.update_metrics).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if plaza_key not in portal.get_final_exempt_plazas():
        print(f"ERROR: plaza key {plaza_key!r} is not in codes_dump.json")
        return 1

    portal.ensure_full_exempt_dirs(process_name)
    portal.save_full_exempt_config(
        process_name,
        plaza_key,
        f"{process_name}_final.xlsx",
        update_exception_metrics=update_metrics,
        plaza_identifier=plaza_identifier,
    )

    print(
        f"Starting Full Exempt Pipeline process={process_name!r} "
        f"plaza_key={plaza_key!r} update_metrics={update_metrics}"
    )
    ok, message = portal.process_full_exempt_pipeline(process_name)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
