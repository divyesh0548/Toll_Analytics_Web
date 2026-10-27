"""Plaza audit exception aggregations for the Audit Exceptions tab."""

from __future__ import annotations

from calendar import month_abbr, monthrange
from collections import defaultdict
from datetime import date
from io import BytesIO

from sqlalchemy import text

from app.extensions import db
from app.models.audit_exception import (
    AuditExceptionMetric,
    AuditExceptionOutputFile,
    AuditExceptionType,
)
from app.models.exception_pipeline import (
    PipelineAuditExceptionMetric,
    PipelineAuditExceptionOutputFile,
)
from app.services.audit_exception_bootstrap import ensure_audit_exception_types
from app.utils.analytics_config import REVENUE_DISTRIBUTION_PER_CLASS_TABLE


MONTH_LABELS = list(month_abbr)  # index 1 = Jan
_MONTH_ABBR_TO_NUM = {
    month_abbr[i].casefold(): i for i in range(1, 13) if month_abbr[i]
}


def _period_label(year: int, month: int | None) -> str:
    if month is None:
        return f"{year} (full year)"
    name = MONTH_LABELS[month] if 1 <= month <= 12 else str(month)
    return f"{name} {year}"


def _period_date_bounds(year: int, month: int | None) -> tuple[date, date]:
    if month is None:
        return date(year, 1, 1), date(year, 12, 31)
    last = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _plaza_period_revenue(plaza_identifier: str, year: int, month: int | None) -> float | None:
    """Sum ETC class revenue for the selected month or full year. None if no rows."""
    start, end = _period_date_bounds(year, month)
    table = REVENUE_DISTRIBUTION_PER_CLASS_TABLE
    if not str(table).replace("_", "").isalnum():
        raise RuntimeError(f"Invalid revenue table name: {table!r}")
    row = db.session.execute(
        text(
            f"""
            SELECT
                COUNT(*)::int AS row_count,
                COALESCE(SUM(revenue), 0)::float AS total
            FROM {table}
            WHERE plaza_identifier = :plaza
              AND date >= :start
              AND date <= :end
            """
        ),
        {"plaza": plaza_identifier, "start": start, "end": end},
    ).mappings().first()
    if not row or int(row["row_count"] or 0) == 0:
        return None
    return float(row["total"] or 0)


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


def _metric_models(*, metrics_source: str):
    """manual = legacy single-run tables; pipeline = one-click tables."""
    if str(metrics_source or "").strip().lower() == "pipeline":
        return PipelineAuditExceptionMetric, PipelineAuditExceptionOutputFile
    return AuditExceptionMetric, AuditExceptionOutputFile


def _load_output_files_by_type(
    plaza_identifier: str,
    *,
    year: int,
    month: int | None,
    metrics_source: str = "manual",
) -> dict[int, list[dict]]:
    """Newest-first output files per exception_type_id matching the selection."""
    _Metric, OutputFile = _metric_models(metrics_source=metrics_source)
    rows = (
        OutputFile.query.filter_by(
            plaza_identifier=plaza_identifier,
            is_final_output=True,
        )
        .order_by(OutputFile.created_at.desc())
        .all()
    )
    by_type: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        if not _output_file_matches(row.month_label, year=year, month=month):
            continue
        by_type[int(row.exception_type_id)].append(row.to_dict())
    return by_type


def _available_periods(plaza_identifier: str, *, metrics_source: str = "manual") -> list[dict]:
    Metric, _Output = _metric_models(metrics_source=metrics_source)
    pair_rows = (
        db.session.query(Metric.year, Metric.month)
        .filter(Metric.plaza_identifier == plaza_identifier)
        .distinct()
        .order_by(Metric.year.desc(), Metric.month.desc())
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
    metrics_source: str = "manual",
) -> dict:
    """
    Build audit exceptions for a plaza.

    - year + month: single calendar month
    - year only (month is None): sum metrics across all months in that year
    - neither: default to the current calendar month
    - metrics_source: "manual" (legacy tables) or "pipeline" (one-click tables)
    """
    ensure_audit_exception_types()
    source = "pipeline" if str(metrics_source or "").strip().lower() == "pipeline" else "manual"
    Metric, _Output = _metric_models(metrics_source=source)

    today = date.today()
    periods = _available_periods(plaza_identifier, metrics_source=source)
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
        metrics = Metric.query.filter_by(
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
                "notes": None,
                "has_metric": False,
            }
        )
        for metric in metrics:
            bucket = totals[metric.exception_type_id]
            bucket["has_metric"] = True
            if metric.percentage is not None:
                bucket["percentage_values"].append(float(metric.percentage))
                continue
            bucket["total_amount"] += float(metric.total_amount or 0)
            bucket["total_count"] += int(metric.total_count or 0)
            # Keep latest non-empty severity/status/notes if present.
            if metric.severity and not bucket["severity"]:
                bucket["severity"] = metric.severity
            if metric.status and not bucket["status"]:
                bucket["status"] = metric.status
            if metric.notes and not bucket["notes"]:
                bucket["notes"] = metric.notes
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
        metrics = Metric.query.filter_by(
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
                "notes": m.notes,
                "has_metric": True,
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
            "notes": None,
            "has_metric": False,
        }
    output_files_by_type = _load_output_files_by_type(
        plaza_identifier, year=year, month=month, metrics_source=source
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
                    "notes": child_metric.get("notes"),
                    "has_metric": bool(child_metric.get("has_metric")),
                    "output_files": list(
                        output_files_by_type.get(int(child.id), [])
                    ),
                }
            )
        if segments:
            total_amount = sum(row["total_amount"] or 0 for row in segments)
            total_count = sum(row["total_count"] or 0 for row in segments)
            percentage = None
            has_metric = any(row.get("has_metric") for row in segments)
        elif metric.get("percentage") is not None:
            total_amount = None
            total_count = None
            percentage = float(metric["percentage"])
            has_metric = bool(metric.get("has_metric"))
        else:
            total_amount = float(metric["total_amount"] or 0)
            total_count = int(metric["total_count"] or 0)
            percentage = None
            has_metric = bool(metric.get("has_metric"))
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
                "notes": metric.get("notes"),
                "has_metric": has_metric,
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

    return _audit_payload(
        plaza_identifier,
        source=source,
        selection=selection,
        periods=periods,
        years=years,
        exceptions=exceptions,
        year=year,
        month=month,
    )


def _audit_payload(
    plaza_identifier: str,
    *,
    source: str,
    selection: dict,
    periods,
    years,
    exceptions: list,
    year: int,
    month: int | None,
) -> dict:
    return {
        "plaza_identifier": plaza_identifier,
        "metrics_source": source,
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
            # Plaza ETC revenue for the selected month/year (denominator for % of Revenue).
            "period_revenue": _plaza_period_revenue(plaza_identifier, year, month),
        },
    }


def audit_exceptions_workbook(payload: dict, *, plaza_name: str) -> bytes:
    """Spreadsheet of the on-screen audit figures. Does not include output files."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Audit exceptions"
    selection = payload.get("selection") or {}
    summary = payload.get("summary") or {}
    sheet.append(["Plaza", plaza_name])
    sheet.append(["Period", selection.get("label") or ""])
    sheet.append(["Metrics source", payload.get("metrics_source") or "manual"])
    sheet.append(["Total transactions", summary.get("total_count")])
    sheet.append(["Total impact (₹)", summary.get("total_amount")])
    sheet.append([])
    sheet.append(
        [
            "Code",
            "Exception",
            "Transactions",
            "Impact (in Lakh)",
            "% of Revenue",
            "Notes",
        ]
    )

    revenue = summary.get("period_revenue")
    lac = 100_000

    def _append(line: dict) -> None:
        percentage = line.get("percentage")
        amount = line.get("total_amount")
        count = line.get("total_count")
        if percentage is not None:
            transactions = None
            impact = f"{float(percentage):.2f}%"
            share = None
        else:
            transactions = count
            impact = None if amount is None else round(float(amount) / lac, 2)
            share = None
            if revenue not in (None, 0) and amount is not None:
                share = round((float(amount) / float(revenue)) * 100, 2)
        sheet.append(
            [
                line.get("code") or "",
                line.get("label") or "",
                transactions,
                impact,
                None if share is None else f"{share:.2f}%",
                line.get("notes") or "",
            ]
        )

    for row in payload.get("exceptions") or []:
        _append(row)
        for segment in row.get("segments") or []:
            _append(segment)

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
