"""Plaza Numbers dashboard and portfolio volume aggregations."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime

import psycopg2
from psycopg2.extras import RealDictCursor

from app.models.plaza import Plaza
from app.models.spv import Spv
from app.services.analytics_db import get_analytics_db_connection_kwargs
from app.utils.analytics_config import (
    CLASS_DISTRIBUTION_PER_LANE_TABLE,
    MOP_DISTRIBUTION_PER_CLASS_TABLE,
    MOP_DISTRIBUTION_PER_LANE_TABLE,
)

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTH_LABELS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def _fetch_all(query: str, params: tuple | list) -> list[dict]:
    with psycopg2.connect(**get_analytics_db_connection_kwargs()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _parse_month(value: str | None) -> tuple[int, int] | None:
    """Parse YYYY-MM → (year, month)."""
    if not value:
        return None
    text = str(value).strip()
    try:
        if len(text) >= 7 and text[4] == "-":
            year = int(text[:4])
            month = int(text[5:7])
            if 1 <= month <= 12:
                return year, month
    except ValueError:
        return None
    return None


def _parse_year(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        year = int(value)
        if 1990 <= year <= 2100:
            return year
    except (TypeError, ValueError):
        return None
    return None


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _ly_window(start: date, end: date) -> tuple[date, date]:
    try:
        return start.replace(year=start.year - 1), end.replace(year=end.year - 1)
    except ValueError:
        return (
            start.replace(year=start.year - 1, day=28),
            end.replace(year=end.year - 1, day=28),
        )


def _hour_start(hour_value) -> int:
    """Parse ETL hour bucket start, e.g. '14-15' → 14, '2-3' → 2."""
    text = str(hour_value or "").strip()
    if not text:
        return 0
    head = text.split("-", 1)[0].strip()
    try:
        return int(head)
    except ValueError:
        return 0


def _hour_row_sort_key(row: dict) -> tuple:
    d = _as_date(row.get("date")) or date.min
    return (d, _hour_start(row.get("hour")), str(row.get("hour") or ""))


def _data_bounds(plaza_identifier: str) -> tuple[date | None, date | None]:
    rows = _fetch_all(
        f"""
        SELECT MIN(date) AS min_date, MAX(date) AS max_date
        FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
        WHERE plaza_identifier = %s
        """,
        (plaza_identifier,),
    )
    if not rows:
        return None, None
    return _as_date(rows[0]["min_date"]), _as_date(rows[0]["max_date"])


def _window_for_period(period: str, as_of: date) -> tuple[date, date]:
    period = (period or "mtd").strip().lower()
    if period == "day":
        return as_of, as_of
    if period == "ytd":
        return date(as_of.year, 1, 1), as_of
    return date(as_of.year, as_of.month, 1), as_of


def _sum_traffic(plaza_identifier: str, start: date, end: date) -> int:
    rows = _fetch_all(
        f"""
        SELECT COALESCE(SUM(txn_count), 0)::bigint AS total
        FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
        WHERE plaza_identifier = %s AND date >= %s AND date <= %s
        """,
        (plaza_identifier, start, end),
    )
    return int(rows[0]["total"]) if rows else 0


def build_plaza_availability(plaza_identifier: str) -> dict:
    """Distinct dates / months / years with traffic for range pickers."""
    min_date, max_date = _data_bounds(plaza_identifier)
    if min_date is None or max_date is None:
        return {
            "has_data": False,
            "min_date": None,
            "max_date": None,
            "dates": [],
            "months": [],
            "years": [],
            "defaults": {},
        }

    date_rows = _fetch_all(
        f"""
        SELECT DISTINCT date
        FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
        WHERE plaza_identifier = %s
        ORDER BY date ASC
        """,
        (plaza_identifier,),
    )
    dates: list[str] = []
    for row in date_rows:
        d = _as_date(row["date"])
        if d is not None:
            dates.append(d.isoformat())

    month_rows = _fetch_all(
        f"""
        SELECT DISTINCT date_trunc('month', date)::date AS month_start
        FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
        WHERE plaza_identifier = %s
        ORDER BY 1 ASC
        """,
        (plaza_identifier,),
    )
    months = []
    for row in month_rows:
        m = _as_date(row["month_start"])
        if m is None:
            continue
        months.append(
            {
                "value": f"{m.year:04d}-{m.month:02d}",
                "label": f"{MONTH_LABELS[m.month - 1]} {m.year}",
            }
        )

    year_rows = _fetch_all(
        f"""
        SELECT DISTINCT EXTRACT(YEAR FROM date)::int AS year
        FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
        WHERE plaza_identifier = %s
        ORDER BY 1 ASC
        """,
        (plaza_identifier,),
    )
    years = [int(r["year"]) for r in year_rows if r.get("year") is not None]

    defaults = {
        "day": {"start": max_date.isoformat(), "end": max_date.isoformat()},
        "mtd": {
            "start": f"{max_date.year:04d}-{max_date.month:02d}",
            "end": f"{max_date.year:04d}-{max_date.month:02d}",
        },
        "ytd": {"start": str(max_date.year), "end": str(max_date.year)},
    }

    return {
        "has_data": True,
        "min_date": min_date.isoformat(),
        "max_date": max_date.isoformat(),
        "dates": dates,
        "months": months,
        "years": years,
        "defaults": defaults,
    }


def _resolve_selection_window(
    period: str,
    *,
    min_date: date,
    max_date: date,
    start_param: str | None = None,
    end_param: str | None = None,
) -> tuple[date, date, bool]:
    """
    Resolve user selection into an inclusive [start, end] window.

    day  → start/end are ISO dates
    mtd  → start/end are YYYY-MM months
    ytd  → start/end are years
    """
    period = (period or "mtd").strip().lower()
    if period not in {"day", "mtd", "ytd"}:
        period = "mtd"

    has_selection = bool(start_param or end_param)

    if period == "day":
        start = _parse_iso_date(start_param) or max_date
        end = _parse_iso_date(end_param) or start
        start = max(min_date, min(start, max_date))
        end = max(min_date, min(end, max_date))
        if start > end:
            start, end = end, start
        return start, end, not has_selection

    if period == "mtd":
        start_m = _parse_month(start_param)
        end_m = _parse_month(end_param)
        if not start_m:
            start_m = (max_date.year, max_date.month)
        if not end_m:
            end_m = start_m
        if start_m > end_m:
            start_m, end_m = end_m, start_m
        start = date(start_m[0], start_m[1], 1)
        end = _month_end(end_m[0], end_m[1])
        start = max(min_date, min(start, max_date))
        end = max(min_date, min(end, max_date))
        if start > end:
            start, end = end, start
        return start, end, not has_selection

    # ytd / year range
    start_y = _parse_year(start_param) or max_date.year
    end_y = _parse_year(end_param) or start_y
    if start_y > end_y:
        start_y, end_y = end_y, start_y
    start = date(start_y, 1, 1)
    end = date(end_y, 12, 31)
    start = max(min_date, min(start, max_date))
    end = max(min_date, min(end, max_date))
    if start > end:
        start, end = end, start
    return start, end, not has_selection


def _pct(part: float, whole: float) -> float | None:
    if whole <= 0:
        return None
    return round(100.0 * part / whole, 1)


def _delta_pct(current: float, previous: float) -> float | None:
    if previous <= 0:
        return None
    return round(100.0 * (current - previous) / previous, 1)


def _empty_payload(period: str, availability: dict | None = None) -> dict:
    return {
        "period": period if period in {"day", "mtd", "ytd"} else "mtd",
        "has_data": False,
        "used_fallback": False,
        "as_of_date": None,
        "latest_date": None,
        "start_date": None,
        "end_date": None,
        "range_label": None,
        "selection": {"start": None, "end": None},
        "trend_grain": "day",
        "availability": availability
        or {
            "has_data": False,
            "min_date": None,
            "max_date": None,
            "dates": [],
            "months": [],
            "years": [],
            "defaults": {},
        },
        "kpis": {
            "traffic_period": None,
            "traffic_today": None,
            "traffic_mtd": None,
            "traffic_ytd": None,
            "etc_share": None,
            "exempt_share": None,
            "cash_share": None,
            "upi_share": None,
            "vs_ly_traffic_pct": None,
            "day_date": None,
            "mtd_start": None,
            "mtd_end": None,
            "ytd_start": None,
            "ytd_end": None,
        },
        "daily_trend": [],
        "class_mix": [],
        "mop_mix": [],
        "lane_throughput": [],
    }


def _selection_echo(period: str, start: date, end: date) -> dict:
    if period == "day":
        return {"start": start.isoformat(), "end": end.isoformat()}
    if period == "mtd":
        return {
            "start": f"{start.year:04d}-{start.month:02d}",
            "end": f"{end.year:04d}-{end.month:02d}",
        }
    return {"start": str(start.year), "end": str(end.year)}


def build_plaza_numbers(
    plaza_identifier: str,
    period: str = "mtd",
    *,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    period = (period or "mtd").strip().lower()
    if period not in {"day", "mtd", "ytd"}:
        period = "mtd"

    availability = build_plaza_availability(plaza_identifier)
    min_date = _parse_iso_date(availability.get("min_date"))
    max_date = _parse_iso_date(availability.get("max_date"))
    if min_date is None or max_date is None:
        return _empty_payload(period, availability)

    win_start, win_end, used_default = _resolve_selection_window(
        period,
        min_date=min_date,
        max_date=max_date,
        start_param=start,
        end_param=end,
    )
    ly_start, ly_end = _ly_window(win_start, win_end)

    # Snapshot KPIs always use the latest available day
    day_start, day_end = _window_for_period("day", max_date)
    mtd_start, mtd_end = _window_for_period("mtd", max_date)
    ytd_start, ytd_end = _window_for_period("ytd", max_date)

    traffic_period = _sum_traffic(plaza_identifier, win_start, win_end)
    traffic_today = _sum_traffic(plaza_identifier, day_start, day_end)
    traffic_mtd = _sum_traffic(plaza_identifier, mtd_start, mtd_end)
    traffic_ytd = _sum_traffic(plaza_identifier, ytd_start, ytd_end)
    traffic_ly = _sum_traffic(plaza_identifier, ly_start, ly_end)

    mop_rows = _fetch_all(
        f"""
        SELECT mop, COALESCE(SUM(txn_count), 0)::bigint AS count
        FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
        WHERE plaza_identifier = %s AND date >= %s AND date <= %s
        GROUP BY mop
        ORDER BY count DESC
        """,
        (plaza_identifier, win_start, win_end),
    )
    mop_mix = [{"mop": r["mop"], "count": int(r["count"])} for r in mop_rows]
    mop_map = {r["mop"]: int(r["count"]) for r in mop_rows}
    etc = mop_map.get("fastag", 0)
    exempt = mop_map.get("exempt", 0)
    cash = mop_map.get("cash", 0)
    upi = mop_map.get("upi", 0)

    class_rows = _fetch_all(
        f"""
        SELECT
          vehicle_class,
          COALESCE(SUM(txn_count), 0)::bigint AS count,
          COALESCE(SUM(CASE WHEN mop = 'fastag' THEN txn_count ELSE 0 END), 0)::bigint AS etc,
          COALESCE(SUM(CASE WHEN mop = 'cash' THEN txn_count ELSE 0 END), 0)::bigint AS cash,
          COALESCE(SUM(CASE WHEN mop = 'upi' THEN txn_count ELSE 0 END), 0)::bigint AS upi,
          COALESCE(SUM(CASE WHEN mop = 'exempt' THEN txn_count ELSE 0 END), 0)::bigint AS exempt
        FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
        WHERE plaza_identifier = %s AND date >= %s AND date <= %s
        GROUP BY vehicle_class
        ORDER BY count DESC
        """,
        (plaza_identifier, win_start, win_end),
    )
    class_ly_rows = _fetch_all(
        f"""
        SELECT vehicle_class, COALESCE(SUM(txn_count), 0)::bigint AS count
        FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
        WHERE plaza_identifier = %s AND date >= %s AND date <= %s
        GROUP BY vehicle_class
        """,
        (plaza_identifier, ly_start, ly_end),
    )
    class_ly = {r["vehicle_class"]: int(r["count"]) for r in class_ly_rows}
    class_mix = []
    for r in class_rows:
        count = int(r["count"])
        class_mix.append(
            {
                "vehicle_class": r["vehicle_class"],
                "count": count,
                "etc": int(r["etc"]),
                "cash": int(r["cash"]),
                "upi": int(r["upi"]),
                "exempt": int(r["exempt"]),
                "vs_ly_pct": _delta_pct(count, class_ly.get(r["vehicle_class"], 0)),
            }
        )

    lane_rows = _fetch_all(
        f"""
        SELECT lane, COALESCE(SUM(txn_count), 0)::bigint AS count
        FROM {MOP_DISTRIBUTION_PER_LANE_TABLE}
        WHERE plaza_identifier = %s AND date >= %s AND date <= %s
        GROUP BY lane
        ORDER BY lane ASC
        """,
        (plaza_identifier, win_start, win_end),
    )
    if not lane_rows:
        lane_rows = _fetch_all(
            f"""
            SELECT lane, COALESCE(SUM(txn_count), 0)::bigint AS count
            FROM {CLASS_DISTRIBUTION_PER_LANE_TABLE}
            WHERE plaza_identifier = %s AND date >= %s AND date <= %s
            GROUP BY lane
            ORDER BY lane ASC
            """,
            (plaza_identifier, win_start, win_end),
        )
    lane_throughput = [{"lane": r["lane"], "count": int(r["count"])} for r in lane_rows]

    span_days = (win_end - win_start).days + 1
    use_hourly = span_days <= 2
    trend_grain = "hour" if use_hourly else "day"

    if use_hourly:
        hourly_rows = _fetch_all(
            f"""
            SELECT date, hour, COALESCE(SUM(txn_count), 0)::bigint AS traffic
            FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
            WHERE plaza_identifier = %s AND date >= %s AND date <= %s
            GROUP BY date, hour
            ORDER BY date ASC, hour ASC
            """,
            (plaza_identifier, win_start, win_end),
        )
        hourly_ly_rows = _fetch_all(
            f"""
            SELECT date, hour, COALESCE(SUM(txn_count), 0)::bigint AS traffic
            FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
            WHERE plaza_identifier = %s AND date >= %s AND date <= %s
            GROUP BY date, hour
            ORDER BY date ASC, hour ASC
            """,
            (plaza_identifier, ly_start, ly_end),
        )
        ly_by_hour = {}
        for r in hourly_ly_rows:
            d = _as_date(r["date"])
            if d is None:
                continue
            ly_by_hour[(d.month, d.day, str(r["hour"]))] = int(r["traffic"])

        daily_trend = []
        for r in sorted(hourly_rows, key=_hour_row_sort_key):
            d = _as_date(r["date"])
            if d is None:
                continue
            hour = str(r["hour"])
            if span_days == 1:
                label = hour
            else:
                label = f"{WEEKDAYS[d.weekday()]} {d.day} {hour}"
            daily_trend.append(
                {
                    "date": d.isoformat(),
                    "hour": hour,
                    "weekday": WEEKDAYS[d.weekday()],
                    "label": label,
                    "traffic": int(r["traffic"]),
                    "traffic_ly": ly_by_hour.get((d.month, d.day, hour)),
                }
            )
    else:
        daily_rows = _fetch_all(
            f"""
            SELECT date, COALESCE(SUM(txn_count), 0)::bigint AS traffic
            FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
            WHERE plaza_identifier = %s AND date >= %s AND date <= %s
            GROUP BY date
            ORDER BY date ASC
            """,
            (plaza_identifier, win_start, win_end),
        )
        daily_ly_rows = _fetch_all(
            f"""
            SELECT date, COALESCE(SUM(txn_count), 0)::bigint AS traffic
            FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
            WHERE plaza_identifier = %s AND date >= %s AND date <= %s
            GROUP BY date
            ORDER BY date ASC
            """,
            (plaza_identifier, ly_start, ly_end),
        )
        ly_by_doy = {}
        for r in daily_ly_rows:
            d = _as_date(r["date"])
            if d is None:
                continue
            ly_by_doy[(d.month, d.day)] = int(r["traffic"])

        daily_trend = []
        for r in daily_rows:
            d = _as_date(r["date"])
            if d is None:
                continue
            daily_trend.append(
                {
                    "date": d.isoformat(),
                    "weekday": WEEKDAYS[d.weekday()],
                    "label": f"{WEEKDAYS[d.weekday()]} {d.day}",
                    "traffic": int(r["traffic"]),
                    "traffic_ly": ly_by_doy.get((d.month, d.day)),
                }
            )

    if win_start == win_end:
        range_label = (
            f"{WEEKDAYS[win_start.weekday()]} {win_start.day} "
            f"{win_start.strftime('%b %Y')}"
        )
    else:
        range_label = (
            f"{win_start.strftime('%d %b %Y')} → {win_end.strftime('%d %b %Y')}"
        )

    return {
        "period": period,
        "has_data": True,
        "used_fallback": used_default,
        "as_of_date": win_end.isoformat(),
        "latest_date": max_date.isoformat(),
        "start_date": win_start.isoformat(),
        "end_date": win_end.isoformat(),
        "range_label": range_label,
        "selection": _selection_echo(period, win_start, win_end),
        "availability": availability,
        "trend_grain": trend_grain,
        "kpis": {
            "traffic_period": traffic_period,
            "traffic_today": traffic_today,
            "traffic_mtd": traffic_mtd,
            "traffic_ytd": traffic_ytd,
            "etc_share": _pct(etc, traffic_period),
            "exempt_share": _pct(exempt, traffic_period),
            "cash_share": _pct(cash, traffic_period),
            "upi_share": _pct(upi, traffic_period),
            "vs_ly_traffic_pct": _delta_pct(traffic_period, traffic_ly),
            "day_date": day_end.isoformat(),
            "mtd_start": mtd_start.isoformat(),
            "mtd_end": mtd_end.isoformat(),
            "ytd_start": ytd_start.isoformat(),
            "ytd_end": ytd_end.isoformat(),
        },
        "daily_trend": daily_trend,
        "class_mix": class_mix,
        "mop_mix": mop_mix,
        "lane_throughput": lane_throughput,
    }


def _plaza_ids_for_company(company_identifier: str) -> list[str]:
    rows = (
        Plaza.query.join(Spv, Plaza.spv_identifier == Spv.spv_identifier)
        .filter(Spv.company_identifier == company_identifier)
        .with_entities(Plaza.plaza_identifier)
        .all()
    )
    return [r[0] for r in rows]


def build_portfolio_volume(companies: list[dict], *, years: int = 5) -> dict:
    """Monthly traffic per company across all its plazas, capped at `years`."""
    today = date.today()
    start = date(today.year - years + 1, 1, 1)
    payload = []

    for company in companies:
        company_id = company["company_identifier"]
        plaza_ids = _plaza_ids_for_company(company_id)
        series: list[dict] = []
        if plaza_ids:
            placeholders = ",".join(["%s"] * len(plaza_ids))
            rows = _fetch_all(
                f"""
                SELECT date_trunc('month', date)::date AS month_start,
                       COALESCE(SUM(txn_count), 0)::bigint AS traffic
                FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
                WHERE plaza_identifier IN ({placeholders})
                  AND date >= %s AND date <= %s
                GROUP BY 1
                ORDER BY 1 ASC
                """,
                (*plaza_ids, start, today),
            )
            for r in rows:
                month_start = _as_date(r["month_start"])
                if month_start is None:
                    continue
                series.append(
                    {
                        "period": month_start.isoformat(),
                        "label": month_start.strftime("%b %Y"),
                        "traffic": int(r["traffic"]),
                    }
                )
        payload.append(
            {
                "company_identifier": company_id,
                "plaza_count": len(plaza_ids),
                "series": series,
            }
        )

    return {"start_date": start.isoformat(), "end_date": today.isoformat(), "companies": payload}
