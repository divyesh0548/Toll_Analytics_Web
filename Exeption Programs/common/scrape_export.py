"""
Dev helper: export vehicles that would be web-scraped, then stop the job.

Website jobs pass E5_SCRAPE_MODE / E6_SCRAPE_MODE = live|export.
Local CLI prompts when stdin is a TTY and the env is unset.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

SCRAPE_EXPORT_EXIT_CODE = 42
SCRAPE_EXPORT_MARKER = "SCRAPE_EXPORT_READY:"


def resolve_scrape_mode(*, env_key: str, default: str = "live") -> str:
    """
    Return 'live' or 'export'.

    Priority: env_key → interactive prompt (TTY) → default.
    """
    raw = (os.environ.get(env_key) or "").strip().lower()
    if raw in {"live", "l", "scrape", "1", "true", "yes", "on"}:
        return "live"
    if raw in {"export", "download", "d", "file", "offline"}:
        return "export"

    if sys.stdin.isatty():
        while True:
            try:
                ans = input(
                    "Vehicles need scraping. "
                    "[L]ive scrape now, or [D]ownload vehicle file and stop? "
                ).strip().lower()
            except EOFError:
                break
            if ans in {"l", "live", ""}:
                return "live"
            if ans in {"d", "download", "export", "file"}:
                return "export"
            print("Please enter L or D.")
    return default if default in {"live", "export"} else "live"


def write_vehicles_export(
    vehicles: pd.DataFrame | list | pd.Series,
    *,
    output_dir: Path,
    program: str,
    vehicle_column: str = "vehicle_reg_no",
) -> Path:
    """Write a one-column CSV of unique non-empty vehicle numbers."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(vehicles, pd.DataFrame):
        if vehicle_column in vehicles.columns:
            series = vehicles[vehicle_column]
        elif len(vehicles.columns) == 1:
            series = vehicles.iloc[:, 0]
        else:
            raise RuntimeError(
                f"Cannot export vehicles — column {vehicle_column!r} not found "
                f"in {list(vehicles.columns)}"
            )
    else:
        series = pd.Series(list(vehicles))

    cleaned = (
        series.astype(str)
        .map(lambda v: str(v or "").strip())
        .loc[lambda s: s.ne("") & s.str.lower().ne("nan")]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    out = pd.DataFrame({vehicle_column: cleaned.tolist()})
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{program}_vehicles_to_scrape_{stamp}.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig")
    print("=" * 60, flush=True)
    print(f"VEHICLES TO SCRAPE: {len(out):,} unique VRN(s) → {path}", flush=True)
    print("=" * 60, flush=True)
    return path


def announce_scrape_export_and_exit(path: Path) -> int:
    """Print marker for the Website worker, then return the special exit code."""
    resolved = Path(path).resolve()
    print(f"{SCRAPE_EXPORT_MARKER}{resolved}", flush=True)
    print(
        "Scrape skipped for offline work. Download this file, scrape vehicles, "
        "attach the scraped result, and Start the job again.",
        flush=True,
    )
    return SCRAPE_EXPORT_EXIT_CODE


def parse_scrape_export_path(stdout: str) -> Path | None:
    """Extract the export path from program stdout, if present."""
    for line in (stdout or "").splitlines():
        text = line.strip()
        if text.startswith(SCRAPE_EXPORT_MARKER):
            raw = text[len(SCRAPE_EXPORT_MARKER) :].strip().strip('"')
            if raw:
                return Path(raw)
    return None
