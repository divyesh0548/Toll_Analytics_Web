"""S3-backed rates and approved-exemption files, valid for a date range."""

from __future__ import annotations

from datetime import date, timedelta

from app.extensions import db
from app.models.plaza_reference_file import REFERENCE_KINDS, PlazaReferenceFile

_OPEN_END = date(9999, 12, 31)


def _end(value: date | None) -> date:
    return value or _OPEN_END


def intervals_overlap(
    left_from: date,
    left_to: date | None,
    right_from: date,
    right_to: date | None,
) -> bool:
    return left_from <= _end(right_to) and right_from <= _end(left_to)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(int(year), int(month), 1)
    if month == 12:
        end = date(int(year), 12, 31)
    else:
        end = date(int(year), int(month) + 1, 1) - timedelta(days=1)
    return start, end


def covers(row: PlazaReferenceFile, start: date, end: date) -> bool:
    """True when the stored interval contains every day from start through end."""
    return row.valid_from <= start and _end(row.valid_to) >= end


def find_covering(
    plaza_identifier: str,
    kind: str,
    start: date,
    end: date,
) -> PlazaReferenceFile | None:
    rows = (
        PlazaReferenceFile.query.filter_by(
            plaza_identifier=plaza_identifier,
            kind=kind,
        )
        .order_by(PlazaReferenceFile.valid_from.desc(), PlazaReferenceFile.id.desc())
        .all()
    )
    for row in rows:
        if covers(row, start, end):
            return row
    return None


def find_overlap(
    plaza_identifier: str,
    kind: str,
    valid_from: date,
    valid_to: date | None,
    *,
    ignore_id: int | None = None,
) -> PlazaReferenceFile | None:
    rows = PlazaReferenceFile.query.filter_by(
        plaza_identifier=plaza_identifier,
        kind=kind,
    ).all()
    for row in rows:
        if ignore_id is not None and row.id == ignore_id:
            continue
        if intervals_overlap(row.valid_from, row.valid_to, valid_from, valid_to):
            return row
    return None


def job_reference_period(job) -> tuple[date, date]:
    """File Upload month when this job belongs to a batch; otherwise today."""
    from app.models.exception_pipeline import ExceptionPipelineBatchStep

    step = ExceptionPipelineBatchStep.query.filter_by(
        child_job_uuid=job.job_uuid
    ).first()
    if step is not None and step.batch is not None:
        return month_bounds(step.batch.year, step.batch.month)
    today = date.today()
    return today, today


def stage_reference_file(job, input_root, kind: str) -> PlazaReferenceFile | None:
    """Download the covering workbook into the job folder. Skip if a file is already there."""
    from pathlib import Path

    from app.services.exception_job_s3 import download_to_path

    if kind not in REFERENCE_KINDS:
        raise ValueError(f"Unknown reference kind: {kind}")
    folder = Path(input_root) / kind
    folder.mkdir(parents=True, exist_ok=True)
    if any(path.is_file() for path in folder.iterdir()):
        return None
    start, end = job_reference_period(job)
    row = find_covering(job.plaza_identifier, kind, start, end)
    if row is None:
        return None
    name = Path(row.original_file_name).name
    if not name or name in {".", ".."}:
        name = "file.xlsx"
    download_to_path(row.s3_key, folder / name)
    return row


def python_rates_available(pipeline_plaza_key: str) -> bool:
    """True when plaza_rates.py has a table for this plaza (either tariff book)."""
    from app.plaza_rates import (
        PLAZA_RATES,
        Plaza_Rates_Apr26_onwards,
        normalize_plaza_rate_key,
    )

    key = normalize_plaza_rate_key(pipeline_plaza_key)
    if not key:
        return False
    return key in PLAZA_RATES or key in Plaza_Rates_Apr26_onwards


def plaza_requires_approved_exemption(pipeline_plaza_key: str) -> bool:
    import sys

    from app.services.exception_program_catalog import exempt_portal_root

    final_dir = (
        exempt_portal_root() / "Scripts" / "Excempy_Query" / "Final_7_scripts"
    )
    if str(final_dir) not in sys.path:
        sys.path.insert(0, str(final_dir))
    try:
        from annexure_plaza_config import uses_approved_exemption_script  # noqa: WPS433
    except Exception:  # noqa: BLE001
        return False
    return bool(uses_approved_exemption_script(pipeline_plaza_key))


def full_exempt_reference_block_reason(
    *,
    plaza_identifier: str,
    pipeline_plaza_key: str | None,
    start: date,
    end: date,
    has_rates_upload: bool = False,
    has_approved_upload: bool = False,
) -> str | None:
    """
    Website Exempt Query does not read local rate or approved-exemption workbooks.

    An uploaded rates file is used when one covers the period. Otherwise the
    server rate table in plaza_rates.py is used. A plaza that needs an
    approved-exemption file cannot run unless that file was uploaded.
    """
    key = str(pipeline_plaza_key or "").strip().upper()
    identifier = str(plaza_identifier or "").strip()
    if plaza_requires_approved_exemption(key):
        approved = (
            find_covering(identifier, "approved_exemption", start, end)
            if identifier and not has_approved_upload
            else None
        )
        if not has_approved_upload and approved is None:
            return (
                "This plaza’s Exempt Query needs an Approved exemption file that "
                "covers this period. Upload it with Configure rates and other files."
            )
    rates = (
        find_covering(identifier, "rates", start, end)
        if identifier and not has_rates_upload
        else None
    )
    if not has_rates_upload and rates is None and not python_rates_available(key):
        return (
            "No rates file covers this period, and this plaza is not in the "
            "server rate table (plaza_rates.py). Upload a rates file with "
            "Configure rates and other files."
        )
    return None
