"""Plaza audit exception aggregations for the Audit Exceptions tab."""

from __future__ import annotations

from calendar import month_abbr
from collections import defaultdict
from datetime import date

from app.extensions import db
from app.models.audit_exception import (
    AuditExceptionMetric,
    AuditExceptionOutputFile,
    AuditExceptionType,
)
from app.services.audit_exception_bootstrap import ensure_audit_exception_types


MONTH_LABELS = list(month_abbr)  # index 1 = Jan
_MONTH_ABBR_TO_NUM = {
    month_abbr[i].casefold(): i for i in range(1, 13) if month_abbr[i]
}


def _period_label(year: int, month: int | None) -> str:
    if month is None:
        return f"{year} (full year)"
    name = MONTH_LABELS[month] if 1 <= month <= 12 else str(month)
    return f"{name} {year}"


def parse_month_label_periods(month_label: str) -> set[tuple[int, int]]:
    """
    Parse output month_label into (year, month) pairs.

    Supported shapes (from common.s3_output_upload):
      2026-Jan
      2026-Apr-May
      2026-Nov-Dec_2027-Jan-Feb
    Also accepts legacy Mon-YYYY / Mon-Mon-YYYY.
    """
    text = str(month_label or "").strip()
    if not text:
        return set()

    pairs: set[tuple[int, int]] = set()
    for part in text.split("_"):
        part = part.strip()
        if not part:
            continue
        tokens = [t.strip() for t in part.split("-") if t.strip()]
        if not tokens:
            continue

        # YEAR-Mon-Mon-...
        if tokens[0].isdigit() and len(tokens[0]) == 4:
            year = int(tokens[0])
            for tok in tokens[1:]:
                month_num = _MONTH_ABBR_TO_NUM.get(tok[:3].casefold())
                if month_num:
                    pairs.add((year, month_num))
            continue

        # Mon-...-YEAR
        if tokens[-1].isdigit() and len(tokens[-1]) == 4:
            year = int(tokens[-1])
            for tok in tokens[:-1]:
                month_num = _MONTH_ABBR_TO_NUM.get(tok[:3].casefold())
                if month_num:
                    pairs.add((year, month_num))

    return pairs


def _output_file_matches(
    month_label: str,
    *,
    year: int,
    month: int | None,
) -> bool:
    periods = parse_month_label_periods(month_label)
    if not periods:
        return False
    if month is None:
        return any(y == year for y, _m in periods)
    return (year, month) in periods


def _load_output_files_by_type(
    plaza_identifier: str,
    *,
    year: int,
    month: int | None,
) -> dict[int, list[dict]]:
    """Newest-first output files per exception_type_id matching the selection."""
    rows = (
        AuditExceptionOutputFile.query.filter_by(
            plaza_identifier=plaza_identifier,
            is_final_output=True,
        )
        .order_by(AuditExceptionOutputFile.created_at.desc())
        .all()
    )
    by_type: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        if not _output_file_matches(row.month_label, year=year, month=month):
            continue
        by_type[int(row.exception_type_id)].append(row.to_dict())
    return by_type


def _available_periods(plaza_identifier: str) -> list[dict]:
    pair_rows = (
        db.session.query(AuditExceptionMetric.year, AuditExceptionMetric.month)
        .filter(AuditExceptionMetric.plaza_identifier == plaza_identifier)
        .distinct()
        .order_by(AuditExceptionMetric.year.desc(), AuditExceptionMetric.month.desc())
        .all()
    )
    return [
        {
            "year": int(year),
            "month": int(month),
            "value": f"{int(year):04d}-{int(month):02d}",
            "label": _period_label(int(year), int(month)),
        }
        for year, month in pair_rows
    ]


def _available_years(periods: list[dict], today: date) -> list[int]:
    years = {int(row["year"]) for row in periods}
    years.add(today.year)
    # Include a small recent window so the year dropdown stays usable with no data.
    for offset in range(0, 6):
        years.add(today.year - offset)
    return sorted(years, reverse=True)


def build_plaza_audit_exceptions(
    plaza_identifier: str,
    *,
    year: int | None = None,
    month: int | None = None,
) -> dict:
    """
    Build audit exceptions for a plaza.

    - year + month: single calendar month
    - year only (month is None): sum metrics across all months in that year
    - neither: default to the current calendar month
    """
    ensure_audit_exception_types()

    today = date.today()
    periods = _available_periods(plaza_identifier)
    years = _available_years(periods, today)

    # Default = current month (not the latest month that happens to have data).
    if year is None:
        year = today.year
        month = today.month
    else:
        year = int(year)
        if month is not None:
            month = int(month)

    if month is not None and not (1 <= month <= 12):
        raise ValueError("month must be between 1 and 12")
    if not (1990 <= year <= 2100):
        raise ValueError("year out of supported range")

    types = (
        AuditExceptionType.query.filter_by(is_active=True, is_hidden=False)
        .order_by(AuditExceptionType.sort_order.asc(), AuditExceptionType.code.asc())
        .all()
    )
    parents = [row for row in types if row.parent_id is None]
    children_by_parent: dict[int, list[AuditExceptionType]] = defaultdict(list)
    for row in types:
        if row.parent_id is not None:
            children_by_parent[row.parent_id].append(row)

    if month is None:
        metrics = AuditExceptionMetric.query.filter_by(
            plaza_identifier=plaza_identifier,
            year=year,
        ).all()
        totals: dict[int, dict] = defaultdict(
            lambda: {
                "total_amount": 0.0,
                "total_count": 0,
                "percentage_values": [],
                "severity": None,
                "status": None,
            }
        )
        for metric in metrics:
            bucket = totals[metric.exception_type_id]
            if metric.percentage is not None:
                bucket["percentage_values"].append(float(metric.percentage))
                continue
            bucket["total_amount"] += float(metric.total_amount or 0)
            bucket["total_count"] += int(metric.total_count or 0)
            # Keep latest non-empty severity/status if present.
            if metric.severity and not bucket["severity"]:
                bucket["severity"] = metric.severity
            if metric.status and not bucket["status"]:
                bucket["status"] = metric.status
        by_type_id = {}
        for type_id, bucket in totals.items():
            percentages = bucket.pop("percentage_values")
            if percentages:
                bucket["percentage"] = round(sum(percentages) / len(percentages), 2)
                bucket["total_amount"] = None
                bucket["total_count"] = None
            else:
                bucket["percentage"] = None
            by_type_id[type_id] = bucket
    else:
        metrics = AuditExceptionMetric.query.filter_by(
            plaza_identifier=plaza_identifier,
            year=year,
            month=month,
        ).all()
        by_type_id = {
            m.exception_type_id: {
                "total_amount": float(m.total_amount) if m.total_amount is not None else None,
                "total_count": int(m.total_count) if m.total_count is not None else None,
                "percentage": float(m.percentage) if m.percentage is not None else None,
                "severity": m.severity,
                "status": m.status,
            }
            for m in metrics
        }

    def _metric_for(type_id: int) -> dict:
        return by_type_id.get(type_id) or {
            "total_amount": 0.0,
            "total_count": 0,
            "percentage": None,
            "severity": None,
            "status": None,
        }

    output_files_by_type = _load_output_files_by_type(
        plaza_identifier, year=year, month=month
    )

    exceptions = []
    for exc_type in parents:
        metric = _metric_for(exc_type.id)
        segments = []
        for child in children_by_parent.get(exc_type.id, []):
            child_metric = _metric_for(child.id)
            segments.append(
                {
                    "code": child.code,
                    "label": child.label,
                    "exception_type_id": child.id,
                    "total_amount": float(child_metric["total_amount"] or 0)
                    if child_metric.get("percentage") is None
                    else None,
                    "total_count": int(child_metric["total_count"] or 0)
                    if child_metric.get("percentage") is None
                    else None,
                    "percentage": child_metric.get("percentage"),
                    "severity": child_metric.get("severity"),
                    "status": child_metric.get("status"),
                    "output_files": list(
                        output_files_by_type.get(int(child.id), [])
                    ),
                }
            )
        if segments:
            total_amount = sum(row["total_amount"] or 0 for row in segments)
            total_count = sum(row["total_count"] or 0 for row in segments)
            percentage = None
        elif metric.get("percentage") is not None:
            total_amount = None
            total_count = None
            percentage = float(metric["percentage"])
        else:
            total_amount = float(metric["total_amount"] or 0)
            total_count = int(metric["total_count"] or 0)
            percentage = None
        exceptions.append(
            {
                "code": exc_type.code,
                "label": exc_type.label,
                "exception_type_id": exc_type.id,
                "total_amount": total_amount,
                "total_count": total_count,
                "percentage": percentage,
                "severity": metric.get("severity"),
                "status": metric.get("status"),
                "output_files": list(
                    output_files_by_type.get(int(exc_type.id), [])
                ),
                "segments": segments,
            }
        )

    if month is None:
        selection = {
            "year": year,
            "month": None,
            "value": f"{year:04d}",
            "label": _period_label(year, None),
            "scope": "year",
        }
    else:
        selection = {
            "year": year,
            "month": month,
            "value": f"{year:04d}-{month:02d}",
            "label": _period_label(year, month),
            "scope": "month",
        }

    return {
        "plaza_identifier": plaza_identifier,
        "selection": selection,
        "availability": {
            "months": periods,
            "years": years,
        },
        "exceptions": exceptions,
        "summary": {
            "total_amount": sum(
                row["total_amount"] for row in exceptions if row["percentage"] is None
            ),
            "total_count": sum(
                row["total_count"] for row in exceptions if row["percentage"] is None
            ),
            "exception_types": len(exceptions),
        },
    }
