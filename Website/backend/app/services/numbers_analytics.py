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
    GAP_DISTRIBUTION_TABLE,
    LANES,
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
        "gap": {
            "overall": {"avg": None, "min": None, "max": None, "lt2_count": 0},
            "by_lane": [],
            "trend": [],
        },
        "class_distribution": {
            "totals": [],
            "trend": {"categories": [], "series": []},
            "by_lane": {"lanes": [], "series": []},
        },
        "mop_distribution": {
            "totals": [],
            "trend": {"categories": [], "series": []},
            "by_lane": {"lanes": [], "series": []},
            "by_class": {"classes": [], "series": []},
        },
        "summary": {
            "by_mop": [],
            "by_class": [],
            "by_lane": [],
            "mop_x_lane": {"lanes": [], "series": []},
            "mop_x_class": {"classes": [], "series": []},
            "class_x_lane": {"lanes": [], "series": []},
        },
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


def _trend_label(d: date, hour: str | None, *, span_days: int, use_hourly: bool) -> str:
    if use_hourly:
        hour_text = str(hour or "")
        if span_days == 1:
            return hour_text
        return f"{WEEKDAYS[d.weekday()]} {d.day} {hour_text}"
    return f"{WEEKDAYS[d.weekday()]} {d.day}"


def _stacked_series(
    categories: list[str],
    keys: list[str],
    values_by_cat_key: dict[tuple[str, str], int],
    *,
    name_key: str = "name",
) -> list[dict]:
    series = []
    for key in keys:
        series.append(
            {
                name_key: key,
                "name": key,
                "data": [int(values_by_cat_key.get((cat, key), 0)) for cat in categories],
            }
        )
    return series


def _build_gap_block(
    plaza_identifier: str,
    win_start: date,
    win_end: date,
    *,
    use_hourly: bool,
    span_days: int,
) -> dict:
    lane_cols = list(LANES.items())  # (L01, l01)
    select_parts = ["date", "hour"]
    for _lane, col in lane_cols:
        select_parts.append(col)
        select_parts.append(f"{col}_lt2_count")
    rows = _fetch_all(
        f"""
        SELECT {", ".join(select_parts)}
        FROM {GAP_DISTRIBUTION_TABLE}
        WHERE plaza_identifier = %s AND date >= %s AND date <= %s
        ORDER BY date ASC, hour ASC
        """,
        (plaza_identifier, win_start, win_end),
    )

    per_lane_values: dict[str, list[float]] = {lane: [] for lane, _ in lane_cols}
    per_lane_lt2: dict[str, int] = {lane: 0 for lane, _ in lane_cols}
    trend_buckets: dict[tuple, dict[str, float | int | str | date]] = {}

    for row in rows:
        d = _as_date(row.get("date"))
        if d is None:
            continue
        hour = str(row.get("hour") or "")
        if use_hourly:
            bucket_key = (d, hour)
        else:
            bucket_key = (d,)

        bucket = trend_buckets.setdefault(
            bucket_key,
            {"date": d, "hour": hour, "sum": 0.0, "n": 0, "lt2": 0},
        )

        for lane, col in lane_cols:
            raw = row.get(col)
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            per_lane_values[lane].append(value)
            bucket["sum"] = float(bucket["sum"]) + value
            bucket["n"] = int(bucket["n"]) + 1

            lt2_raw = row.get(f"{col}_lt2_count")
            try:
                lt2 = int(lt2_raw or 0)
            except (TypeError, ValueError):
                lt2 = 0
            per_lane_lt2[lane] += lt2
            bucket["lt2"] = int(bucket["lt2"]) + lt2

    by_lane = []
    all_values: list[float] = []
    total_lt2 = 0
    for lane, _ in lane_cols:
        values = per_lane_values[lane]
        if not values:
            continue
        all_values.extend(values)
        lt2 = per_lane_lt2[lane]
        total_lt2 += lt2
        by_lane.append(
            {
                "lane": lane,
                "avg": round(sum(values) / len(values), 2),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "lt2_count": lt2,
            }
        )

    overall = {
        "avg": round(sum(all_values) / len(all_values), 2) if all_values else None,
        "min": round(min(all_values), 2) if all_values else None,
        "max": round(max(all_values), 2) if all_values else None,
        "lt2_count": total_lt2,
    }

    trend = []
    for key in sorted(trend_buckets.keys(), key=lambda k: (k[0], str(k[1]) if len(k) > 1 else "")):
        bucket = trend_buckets[key]
        d = bucket["date"]
        assert isinstance(d, date)
        hour = str(bucket.get("hour") or "")
        n = int(bucket["n"])
        avg = round(float(bucket["sum"]) / n, 2) if n else None
        trend.append(
            {
                "date": d.isoformat(),
                "hour": hour if use_hourly else None,
                "label": _trend_label(d, hour if use_hourly else None, span_days=span_days, use_hourly=use_hourly),
                "avg_gap": avg,
                "lt2_count": int(bucket["lt2"]),
            }
        )

    return {"overall": overall, "by_lane": by_lane, "trend": trend}


def _build_class_distribution_block(
    plaza_identifier: str,
    win_start: date,
    win_end: date,
    *,
    use_hourly: bool,
    span_days: int,
    class_mix: list[dict],
) -> dict:
    totals = [
        {"vehicle_class": row["vehicle_class"], "count": int(row["count"])}
        for row in class_mix
    ]
    class_order = [row["vehicle_class"] for row in totals]

    if use_hourly:
        trend_rows = _fetch_all(
            f"""
            SELECT date, hour, vehicle_class, COALESCE(SUM(txn_count), 0)::bigint AS count
            FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
            WHERE plaza_identifier = %s AND date >= %s AND date <= %s
            GROUP BY date, hour, vehicle_class
            ORDER BY date ASC, hour ASC
            """,
            (plaza_identifier, win_start, win_end),
        )
    else:
        trend_rows = _fetch_all(
            f"""
            SELECT date, vehicle_class, COALESCE(SUM(txn_count), 0)::bigint AS count
            FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
            WHERE plaza_identifier = %s AND date >= %s AND date <= %s
            GROUP BY date, vehicle_class
            ORDER BY date ASC
            """,
            (plaza_identifier, win_start, win_end),
        )

    category_keys: list[tuple] = []
    category_labels: dict[tuple, str] = {}
    values: dict[tuple[str, str], int] = {}
    seen_classes: set[str] = set(class_order)

    for row in trend_rows:
        d = _as_date(row["date"])
        if d is None:
            continue
        vehicle_class = str(row["vehicle_class"])
        seen_classes.add(vehicle_class)
        if use_hourly:
            hour = str(row.get("hour") or "")
            key = (d, hour)
            label = _trend_label(d, hour, span_days=span_days, use_hourly=True)
        else:
            key = (d,)
            label = _trend_label(d, None, span_days=span_days, use_hourly=False)
        if key not in category_labels:
            category_keys.append(key)
            category_labels[key] = label
        cat_label = category_labels[key]
        values[(cat_label, vehicle_class)] = int(row["count"])

    categories = [category_labels[k] for k in category_keys]
    ordered_classes = class_order + sorted(seen_classes - set(class_order))
    trend_series = _stacked_series(categories, ordered_classes, values)

    lane_rows = _fetch_all(
        f"""
        SELECT lane, vehicle_class, COALESCE(SUM(txn_count), 0)::bigint AS count
        FROM {CLASS_DISTRIBUTION_PER_LANE_TABLE}
        WHERE plaza_identifier = %s AND date >= %s AND date <= %s
        GROUP BY lane, vehicle_class
        ORDER BY lane ASC, count DESC
        """,
        (plaza_identifier, win_start, win_end),
    )
    lanes: list[str] = []
    lane_values: dict[tuple[str, str], int] = {}
    lane_classes: set[str] = set()
    for row in lane_rows:
        lane = str(row["lane"])
        vehicle_class = str(row["vehicle_class"])
        if lane not in lanes:
            lanes.append(lane)
        lane_classes.add(vehicle_class)
        lane_values[(lane, vehicle_class)] = int(row["count"])

    lane_class_order = [c for c in ordered_classes if c in lane_classes] + sorted(
        lane_classes - set(ordered_classes)
    )
    by_lane_series = _stacked_series(lanes, lane_class_order, lane_values)

    return {
        "totals": totals,
        "trend": {"categories": categories, "series": trend_series},
        "by_lane": {"lanes": lanes, "series": by_lane_series},
    }


def _build_mop_distribution_block(
    plaza_identifier: str,
    win_start: date,
    win_end: date,
    *,
    use_hourly: bool,
    span_days: int,
    mop_mix: list[dict],
) -> dict:
    totals = [{"mop": row["mop"], "count": int(row["count"])} for row in mop_mix]
    mop_order = [row["mop"] for row in totals]

    if use_hourly:
        trend_rows = _fetch_all(
            f"""
            SELECT date, hour, mop, COALESCE(SUM(txn_count), 0)::bigint AS count
            FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
            WHERE plaza_identifier = %s AND date >= %s AND date <= %s
            GROUP BY date, hour, mop
            ORDER BY date ASC, hour ASC
            """,
            (plaza_identifier, win_start, win_end),
        )
    else:
        trend_rows = _fetch_all(
            f"""
            SELECT date, mop, COALESCE(SUM(txn_count), 0)::bigint AS count
            FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
            WHERE plaza_identifier = %s AND date >= %s AND date <= %s
            GROUP BY date, mop
            ORDER BY date ASC
            """,
            (plaza_identifier, win_start, win_end),
        )

    category_keys: list[tuple] = []
    category_labels: dict[tuple, str] = {}
    values: dict[tuple[str, str], int] = {}
    seen_mops: set[str] = set(mop_order)

    for row in trend_rows:
        d = _as_date(row["date"])
        if d is None:
            continue
        mop = str(row["mop"])
        seen_mops.add(mop)
        if use_hourly:
            hour = str(row.get("hour") or "")
            key = (d, hour)
            label = _trend_label(d, hour, span_days=span_days, use_hourly=True)
        else:
            key = (d,)
            label = _trend_label(d, None, span_days=span_days, use_hourly=False)
        if key not in category_labels:
            category_keys.append(key)
            category_labels[key] = label
        values[(category_labels[key], mop)] = int(row["count"])

    categories = [category_labels[k] for k in category_keys]
    ordered_mops = mop_order + sorted(seen_mops - set(mop_order))
    trend_series = _stacked_series(categories, ordered_mops, values)

    lane_rows = _fetch_all(
        f"""
        SELECT lane, mop, COALESCE(SUM(txn_count), 0)::bigint AS count
        FROM {MOP_DISTRIBUTION_PER_LANE_TABLE}
        WHERE plaza_identifier = %s AND date >= %s AND date <= %s
        GROUP BY lane, mop
        ORDER BY lane ASC, count DESC
        """,
        (plaza_identifier, win_start, win_end),
    )
    lanes: list[str] = []
    lane_values: dict[tuple[str, str], int] = {}
    lane_mops: set[str] = set()
    for row in lane_rows:
        lane = str(row["lane"])
        mop = str(row["mop"])
        if lane not in lanes:
            lanes.append(lane)
        lane_mops.add(mop)
        lane_values[(lane, mop)] = int(row["count"])
    lane_mop_order = [m for m in ordered_mops if m in lane_mops] + sorted(
        lane_mops - set(ordered_mops)
    )
    by_lane_series = _stacked_series(lanes, lane_mop_order, lane_values)

    class_rows = _fetch_all(
        f"""
        SELECT vehicle_class, mop, COALESCE(SUM(txn_count), 0)::bigint AS count
        FROM {MOP_DISTRIBUTION_PER_CLASS_TABLE}
        WHERE plaza_identifier = %s AND date >= %s AND date <= %s
        GROUP BY vehicle_class, mop
        ORDER BY vehicle_class ASC, count DESC
        """,
        (plaza_identifier, win_start, win_end),
    )
    classes: list[str] = []
    class_values: dict[tuple[str, str], int] = {}
    class_mops: set[str] = set()
    for row in class_rows:
        vehicle_class = str(row["vehicle_class"])
        mop = str(row["mop"])
        if vehicle_class not in classes:
            classes.append(vehicle_class)
        class_mops.add(mop)
        class_values[(vehicle_class, mop)] = int(row["count"])
    class_mop_order = [m for m in ordered_mops if m in class_mops] + sorted(
        class_mops - set(ordered_mops)
    )
    by_class_series = _stacked_series(classes, class_mop_order, class_values)

    return {
        "totals": totals,
        "trend": {"categories": categories, "series": trend_series},
        "by_lane": {"lanes": lanes, "series": by_lane_series},
        "by_class": {"classes": classes, "series": by_class_series},
    }


def _build_summary_block(
    mop_mix: list[dict],
    class_mix: list[dict],
    lane_throughput: list[dict],
    mop_distribution: dict,
    class_distribution: dict,
) -> dict:
    return {
        "by_mop": [{"mop": r["mop"], "count": int(r["count"])} for r in mop_mix],
        "by_class": [
            {"vehicle_class": r["vehicle_class"], "count": int(r["count"])}
            for r in class_mix
        ],
        "by_lane": [
            {"lane": r["lane"], "count": int(r["count"])} for r in lane_throughput
        ],
        "mop_x_lane": mop_distribution.get("by_lane") or {"lanes": [], "series": []},
        "mop_x_class": mop_distribution.get("by_class")
        or {"classes": [], "series": []},
        "class_x_lane": class_distribution.get("by_lane") or {"lanes": [], "series": []},
    }


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

    gap = _build_gap_block(
        plaza_identifier,
        win_start,
        win_end,
        use_hourly=use_hourly,
        span_days=span_days,
    )
    class_distribution = _build_class_distribution_block(
        plaza_identifier,
        win_start,
        win_end,
        use_hourly=use_hourly,
        span_days=span_days,
        class_mix=class_mix,
    )
    mop_distribution = _build_mop_distribution_block(
        plaza_identifier,
        win_start,
        win_end,
        use_hourly=use_hourly,
        span_days=span_days,
        mop_mix=mop_mix,
    )
    summary = _build_summary_block(
        mop_mix,
        class_mix,
        lane_throughput,
        mop_distribution,
        class_distribution,
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
        "gap": gap,
        "class_distribution": class_distribution,
        "mop_distribution": mop_distribution,
        "summary": summary,
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
