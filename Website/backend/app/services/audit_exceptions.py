"""Plaza audit exception aggregations for the Audit Exceptions tab."""

from __future__ import annotations

from calendar import month_abbr
from collections import defaultdict
from datetime import date

from app.extensions import db
from app.models.audit_exception import AuditExceptionMetric, AuditExceptionType
from app.services.audit_exception_bootstrap import ensure_audit_exception_types


MONTH_LABELS = list(month_abbr)  # index 1 = Jan


def _period_label(year: int, month: int | None) -> str:
    if month is None:
        return f"{year} (full year)"
    name = MONTH_LABELS[month] if 1 <= month <= 12 else str(month)
    return f"{name} {year}"


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

    if month is None:
        metrics = AuditExceptionMetric.query.filter_by(
            plaza_identifier=plaza_identifier,
            year=year,
        ).all()
        totals: dict[int, dict] = defaultdict(
            lambda: {"total_amount": 0.0, "total_count": 0, "severity": None, "status": None}
        )
        for metric in metrics:
            bucket = totals[metric.exception_type_id]
            bucket["total_amount"] += float(metric.total_amount or 0)
            bucket["total_count"] += int(metric.total_count or 0)
            # Keep latest non-empty severity/status if present.
            if metric.severity and not bucket["severity"]:
                bucket["severity"] = metric.severity
            if metric.status and not bucket["status"]:
                bucket["status"] = metric.status
        by_type_id = totals
    else:
        metrics = AuditExceptionMetric.query.filter_by(
            plaza_identifier=plaza_identifier,
            year=year,
            month=month,
        ).all()
        by_type_id = {
            m.exception_type_id: {
                "total_amount": float(m.total_amount) if m else 0.0,
                "total_count": int(m.total_count) if m else 0,
                "severity": m.severity,
                "status": m.status,
            }
            for m in metrics
        }

    exceptions = []
    for exc_type in types:
        metric = by_type_id.get(exc_type.id) or {
            "total_amount": 0.0,
            "total_count": 0,
            "severity": None,
            "status": None,
        }
        exceptions.append(
            {
                "code": exc_type.code,
                "label": exc_type.label,
                "exception_type_id": exc_type.id,
                "total_amount": float(metric["total_amount"] or 0),
                "total_count": int(metric["total_count"] or 0),
                "severity": metric.get("severity"),
                "status": metric.get("status"),
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
            "total_amount": sum(row["total_amount"] for row in exceptions),
            "total_count": sum(row["total_count"] for row in exceptions),
            "exception_types": len(exceptions),
        },
    }
