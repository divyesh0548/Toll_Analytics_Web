"""Aggregation helpers for dashboard time buckets."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd

from app.utils.analytics_config import DEFAULT_TOP_LANES, LANES, MOP_TYPES, VEHICLE_CLASSES


def hour_sort_key(hour_label: str) -> int:
    return int(str(hour_label).split("-")[0])


def hour_label(start_hour: int) -> str:
    return f"{start_hour}-{start_hour + 1}"


def hour_labels_for_window(start_hour: int, count: int = 6) -> list[str]:
    return [hour_label(start_hour + offset) for offset in range(count)]


def hour_labels_from_range(start_hour: int, end_hour: int) -> list[str]:
    """Build hour bucket labels from an inclusive start and exclusive end hour index."""
    return hour_labels_for_window(start_hour, max(0, end_hour - start_hour))


def format_hour_window(hour_labels: list[str]) -> str:
    if not hour_labels:
        return ""
    if len(hour_labels) == 1:
        return hour_labels[0]
    start = str(hour_labels[0]).split("-")[0]
    end = str(hour_labels[-1]).split("-")[1]
    return f"{start}-{end}"


def format_short_date_label(value: date | pd.Timestamp) -> str:
    """Month + day only, e.g. 'Jul 10'."""
    if isinstance(value, pd.Timestamp):
        value = value.date()
    return f"{value.strftime('%b')} {value.day}"


def _metric_columns(df: pd.DataFrame) -> list[str]:
    metric_columns = list({**VEHICLE_CLASSES, **LANES, **MOP_TYPES}.values())
    if "total_transaction" in df.columns:
        metric_columns = ["total_transaction", *metric_columns]
    return [column for column in metric_columns if column in df.columns]


def sort_by_hour(df: pd.DataFrame, hour_col: str = "hour") -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["_hour_sort"] = out[hour_col].map(hour_sort_key)
    out = out.sort_values("_hour_sort").drop(columns="_hour_sort")
    return out


def melt_metric_columns(
    df: pd.DataFrame,
    x_col: str,
    column_map: dict[str, str],
    x_order: list | None = None,
    series_order: list | None = None,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[x_col, "series", "count"])

    value_vars = [col for col in column_map.values() if col in df.columns]
    label_lookup = {col: label for label, col in column_map.items()}

    long_df = df.melt(
        id_vars=[x_col],
        value_vars=value_vars,
        var_name="_col",
        value_name="count",
    )
    long_df["series"] = long_df["_col"].map(label_lookup)
    long_df = long_df.drop(columns="_col")

    if x_order is not None:
        categories = [str(value) for value in x_order]
        long_df[x_col] = pd.Categorical(long_df[x_col], categories=categories, ordered=True)
    else:
        long_df[x_col] = long_df[x_col].astype(str)

    if series_order is not None:
        series_categories = [str(value) for value in series_order]
        long_df["series"] = pd.Categorical(long_df["series"], categories=series_categories, ordered=True)

    long_df = long_df.sort_values([x_col, "series"])
    return long_df


def series_order_by_total(long_df: pd.DataFrame) -> list[str]:
    if long_df.empty:
        return []
    totals = long_df.groupby("series", observed=False)["count"].sum()
    ranked = totals.sort_values(ascending=False)
    return [str(name) for name in ranked.index]


def series_order_from_labels(long_df: pd.DataFrame, labels: list[str]) -> list[str]:
    present = {str(value) for value in long_df["series"].astype(str)}
    return [str(label) for label in labels if str(label) in present]


def melt_time_buckets_by_category(
    chart_df: pd.DataFrame,
    column_map: dict[str, str],
    bucket_col: str,
    bucket_order: list[str],
    x_col: str = "category",
) -> tuple[pd.DataFrame, str, list[str], list[str]]:
    """Pivot time-bucket rows so categories are on the x-axis and each bucket is a line."""
    categories = [label for label, col in column_map.items() if col in chart_df.columns]
    buckets_sorted = [str(label) for label in bucket_order]
    rows: list[dict] = []

    normalized_df = chart_df.copy()
    if bucket_col in normalized_df.columns:
        normalized_df[bucket_col] = normalized_df[bucket_col].astype(str)

    for bucket_text in buckets_sorted:
        bucket_rows = normalized_df[normalized_df[bucket_col] == bucket_text]
        source = bucket_rows.iloc[0] if not bucket_rows.empty else None
        for label, col in column_map.items():
            if col not in chart_df.columns:
                continue
            if source is not None and col in source.index and pd.notna(source[col]):
                count = int(source[col])
            else:
                count = 0
            rows.append({x_col: label, "series": bucket_text, "count": count})

    long_df = pd.DataFrame(rows, columns=[x_col, "series", "count"])
    if long_df.empty:
        return long_df, x_col, categories, buckets_sorted

    long_df[x_col] = pd.Categorical(long_df[x_col], categories=categories, ordered=True)
    long_df["series"] = pd.Categorical(long_df["series"], categories=buckets_sorted, ordered=True)
    return long_df.sort_values([x_col, "series"]), x_col, categories, buckets_sorted


def melt_hours_by_category(
    chart_df: pd.DataFrame,
    column_map: dict[str, str],
    hour_labels: list[str],
    x_col: str = "category",
) -> tuple[pd.DataFrame, str, list[str], list[str]]:
    return melt_time_buckets_by_category(chart_df, column_map, "hour", hour_labels, x_col)


def top_lanes_by_volume(df: pd.DataFrame, top_n: int = DEFAULT_TOP_LANES) -> list[str]:
    if df.empty:
        return []
    lane_totals = {lane: int(df[col].sum()) for lane, col in LANES.items() if col in df.columns}
    ranked = sorted(lane_totals.items(), key=lambda item: item[1], reverse=True)
    return [lane for lane, count in ranked[:top_n] if count > 0]


def active_lane_map(chart_df: pd.DataFrame) -> dict[str, str]:
    """Lanes that have a non-zero count in the filtered chart data."""
    return {
        lane: col
        for lane, col in LANES.items()
        if col in chart_df.columns and int(chart_df[col].sum()) > 0
    }


def category_totals_table(chart_df: pd.DataFrame, column_map: dict[str, str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for label, col in column_map.items():
        if col not in chart_df.columns:
            continue
        count = int(chart_df[col].sum())
        if count <= 0:
            continue
        rows.append({"Category": label, "Count": count})

    if not rows:
        return pd.DataFrame(columns=["Category", "Count"])

    return (
        pd.DataFrame(rows)
        .sort_values("Count", ascending=False)
        .reset_index(drop=True)
    )


def aggregate_hourly_window(df: pd.DataFrame, selected_date: date, hour_labels: list[str]) -> pd.DataFrame:
    subset = df[(df["date"] == selected_date) & (df["hour"].isin(hour_labels))].copy()

    metric_columns = [
        column
        for column in df.columns
        if column not in {"id", "plaza_name", "hour", "date"}
    ]

    if not subset.empty:
        grouped = subset.groupby("hour", as_index=False).sum(numeric_only=True)
        grouped["hour"] = grouped["hour"].astype(str)
    else:
        grouped = pd.DataFrame()

    rows: list[dict] = []
    for hour in sorted(hour_labels, key=hour_sort_key):
        hour_text = str(hour)
        if not grouped.empty and hour_text in grouped["hour"].values:
            row = grouped[grouped["hour"] == hour_text].iloc[0].to_dict()
        else:
            row = {"hour": hour_text}
            for column in metric_columns:
                row[column] = 0
        rows.append(row)

    return pd.DataFrame(rows)


def aggregate_daily_range(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """One x-axis node per calendar day in [start, end], including zero-volume days."""
    metric_columns = _metric_columns(df)
    day_count = (end - start).days + 1
    if day_count <= 0:
        return pd.DataFrame()

    subset = df[(df["date"] >= start) & (df["date"] <= end)].copy()
    totals_by_date: dict[date, dict[str, int]] = {}
    if not subset.empty:
        subset["_date"] = pd.to_datetime(subset["date"]).dt.date
        grouped = subset.groupby("_date", as_index=False).sum(numeric_only=True)
        for _, row in grouped.iterrows():
            record_date = row["_date"]
            totals_by_date[record_date] = {
                column: int(row[column]) if column in row.index and pd.notna(row[column]) else 0
                for column in metric_columns
            }

    rows: list[dict] = []
    for offset in range(day_count):
        record_date = start + timedelta(days=offset)
        row: dict = {
            "date": format_short_date_label(record_date),
            "record_date": record_date,
        }
        day_totals = totals_by_date.get(record_date, {})
        for column in metric_columns:
            row[column] = day_totals.get(column, 0)
        rows.append(row)

    return pd.DataFrame(rows)


def aggregate_monthly_daily(df: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    """Backward-compatible wrapper for a single month (all calendar days)."""
    return aggregate_month_span(df, [(year, month)])


def aggregate_month_span(
    df: pd.DataFrame,
    year_months: list[tuple[int, int]],
) -> pd.DataFrame:
    """
    Aggregate selected months onto ~30 x-axis points.
    1 month → every day; 2 months → every 2nd day; N months → every Nth day.
    """
    if not year_months:
        return pd.DataFrame()

    ordered = sorted({(int(year), int(month)) for year, month in year_months})
    stride = max(1, len(ordered))
    metric_columns = _metric_columns(df)

    calendar_days: list[date] = []
    for year, month in ordered:
        last_day = calendar.monthrange(year, month)[1]
        calendar_days.extend(date(year, month, day) for day in range(1, last_day + 1))

    sampled_days = calendar_days[::stride]
    if not sampled_days:
        return pd.DataFrame()

    subset = df.copy()
    if not subset.empty:
        subset["_date"] = pd.to_datetime(subset["date"]).dt.date

    rows: list[dict] = []
    for record_date in sampled_days:
        day_subset = subset[subset["_date"] == record_date] if not subset.empty else subset
        row: dict = {
            "date": format_short_date_label(record_date),
            "record_date": record_date,
            "day_label": format_short_date_label(record_date),
        }
        for column in metric_columns:
            if column in df.columns:
                row[column] = int(day_subset[column].sum()) if not day_subset.empty else 0
            else:
                row[column] = 0
        rows.append(row)

    return pd.DataFrame(rows)


def aggregate_monthly_parts(df: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    return aggregate_monthly_daily(df, year, month)


def total_volume(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    if "total_transaction" in df.columns:
        return int(df["total_transaction"].sum())
    class_cols = [col for col in VEHICLE_CLASSES.values() if col in df.columns]
    if class_cols:
        return int(df[class_cols].sum().sum())
    lane_cols = [col for col in LANES.values() if col in df.columns]
    if lane_cols:
        return int(df[lane_cols].sum().sum())
    mop_cols = [col for col in MOP_TYPES.values() if col in df.columns]
    if mop_cols:
        return int(df[mop_cols].sum().sum())
    return 0


def format_total_kpi(df: pd.DataFrame) -> str:
    return f"{total_volume(df):,}"


def metric_share_pct_df(chart_df: pd.DataFrame, column_map: dict[str, str]) -> pd.DataFrame:
    """Replace category columns with % of that row's category total (hour/day share)."""
    if chart_df.empty:
        return chart_df

    out = chart_df.copy()
    cols = [col for col in column_map.values() if col in out.columns]
    if not cols:
        return out

    for col in cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    row_total = out[cols].sum(axis=1)
    safe_total = row_total.replace(0, pd.NA)
    for col in cols:
        out[col] = (out[col] / safe_total * 100.0).fillna(0.0)
    return out


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float | None:
    vals = pd.to_numeric(values, errors="coerce")
    wts = pd.to_numeric(weights, errors="coerce").fillna(0)
    mask = vals.notna() & (wts > 0)
    if not mask.any():
        return None
    return float((vals[mask] * wts[mask]).sum() / wts[mask].sum())


def filter_gap_df(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Filter gap distribution rows by Hours / Day on day / Month params."""
    if df.empty:
        return df

    mode = params["mode"]
    if mode == "Hours":
        return df[
            (df["date"] == params["selected_date"]) & (df["hour"].isin(params["hour_labels"]))
        ].copy()

    if mode == "Day on day":
        return df[
            (df["date"] >= params["start_date"]) & (df["date"] <= params["end_date"])
        ].copy()

    year_months = params.get("year_months") or [(params["year"], params["month"])]
    masks = []
    for year, month in year_months:
        month_start = date(year, month, 1)
        month_end = date(year, month, calendar.monthrange(year, month)[1])
        masks.append((df["date"] >= month_start) & (df["date"] <= month_end))
    if not masks:
        return df.iloc[0:0].copy()
    combined = masks[0]
    for mask in masks[1:]:
        combined = combined | mask
    return df[combined].copy()


def _aggregate_gap_group(group: pd.DataFrame) -> dict:
    gap_count = int(pd.to_numeric(group["gap_count"], errors="coerce").fillna(0).sum())
    vehicle_count = int(pd.to_numeric(group["vehicle_count"], errors="coerce").fillna(0).sum())
    lt2_count = 0
    if "gap_lt_2s_count" in group.columns:
        lt2_count = int(pd.to_numeric(group["gap_lt_2s_count"], errors="coerce").fillna(0).sum())
    return {
        "vehicle_count": vehicle_count,
        "gap_count": gap_count,
        "gap_lt_2s_count": lt2_count,
        "avg_gap_sec": _weighted_mean(group["avg_gap_sec"], group["gap_count"]),
        "median_gap_sec": _weighted_mean(group["median_gap_sec"], group["gap_count"]),
        "p10_gap_sec": _weighted_mean(group["p10_gap_sec"], group["gap_count"]),
        "p90_gap_sec": _weighted_mean(group["p90_gap_sec"], group["gap_count"]),
        "min_gap_sec": float(pd.to_numeric(group["min_gap_sec"], errors="coerce").min())
        if group["min_gap_sec"].notna().any()
        else None,
        "max_gap_sec": float(pd.to_numeric(group["max_gap_sec"], errors="coerce").max())
        if group["max_gap_sec"].notna().any()
        else None,
    }


def _empty_gap_lane_row(x_col: str, x_value: str, lane: str) -> dict:
    return {
        x_col: x_value,
        "lane_no": lane,
        "vehicle_count": 0,
        "gap_count": 0,
        "gap_lt_2s_count": 0,
        "avg_gap_sec": None,
        "median_gap_sec": None,
        "p10_gap_sec": None,
        "p90_gap_sec": None,
        "min_gap_sec": None,
        "max_gap_sec": None,
    }


def month_span_sample_dates(year_months: list[tuple[int, int]]) -> list[date]:
    """Calendar days across selected months, sampled every N months → ~30 points."""
    ordered = sorted({(int(year), int(month)) for year, month in year_months})
    if not ordered:
        return []
    stride = max(1, len(ordered))
    calendar_days: list[date] = []
    for year, month in ordered:
        last_day = calendar.monthrange(year, month)[1]
        calendar_days.extend(date(year, month, day) for day in range(1, last_day + 1))
    return calendar_days[::stride]


def build_gap_time_series(
    df: pd.DataFrame,
    params: dict,
) -> tuple[pd.DataFrame, str, list | None, bool, str]:
    """
    Aggregate gap rows for line charts.
    Returns long-friendly frame with one row per time bucket × lane.
    """
    mode = params["mode"]
    filtered = filter_gap_df(df, params)
    if filtered.empty:
        if mode == "Hours":
            return filtered, "hour", [str(label) for label in params.get("hour_labels", [])], False, mode
        if mode == "Day on day":
            start = params["start_date"]
            end = params["end_date"]
            x_order = [
                format_short_date_label(start + timedelta(days=offset))
                for offset in range((end - start).days + 1)
            ]
            return filtered, "date", x_order, False, mode
        year_months = params.get("year_months") or [(params["year"], params["month"])]
        x_order = [format_short_date_label(value) for value in month_span_sample_dates(year_months)]
        return filtered, "date", x_order, False, mode

    if mode == "Hours":
        out = filtered.copy()
        out["hour"] = out["hour"].astype(str)
        x_order = [str(label) for label in sorted(params["hour_labels"], key=hour_sort_key)]
        return out, "hour", x_order, False, mode

    if mode == "Day on day":
        start = params["start_date"]
        end = params["end_date"]
        x_dates = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
        x_order = [format_short_date_label(value) for value in x_dates]
        lanes = sorted(filtered["lane_no"].astype(str).unique().tolist())
        filtered = filtered.copy()
        filtered["_date"] = pd.to_datetime(filtered["date"]).dt.date

        rows: list[dict] = []
        for record_date in x_dates:
            day_subset = filtered[filtered["_date"] == record_date]
            label = format_short_date_label(record_date)
            if day_subset.empty:
                for lane in lanes:
                    rows.append(_empty_gap_lane_row("date", label, lane))
                continue
            for lane_no, group in day_subset.groupby("lane_no", sort=True):
                rows.append(
                    {
                        "date": label,
                        "lane_no": lane_no,
                        **_aggregate_gap_group(group),
                    }
                )
        out = pd.DataFrame(rows)
        return out, "date", x_order, False, mode

    year_months = params.get("year_months") or [(params["year"], params["month"])]
    x_dates = month_span_sample_dates(year_months)
    x_order = [format_short_date_label(value) for value in x_dates]
    lanes = sorted(filtered["lane_no"].astype(str).unique().tolist())
    filtered = filtered.copy()
    filtered["_date"] = pd.to_datetime(filtered["date"]).dt.date

    rows = []
    for record_date in x_dates:
        day_subset = filtered[filtered["_date"] == record_date]
        label = format_short_date_label(record_date)
        if day_subset.empty:
            for lane in lanes:
                rows.append(_empty_gap_lane_row("date", label, lane))
            continue
        for lane_no, group in day_subset.groupby("lane_no", sort=True):
            rows.append(
                {
                    "date": label,
                    "lane_no": lane_no,
                    **_aggregate_gap_group(group),
                }
            )
    out = pd.DataFrame(rows)
    return out, "date", x_order, False, mode


def gap_avg_long_df(
    chart_df: pd.DataFrame,
    x_col: str,
    x_order: list | None,
    selected_lanes: list[str] | None = None,
) -> pd.DataFrame:
    if chart_df.empty:
        return pd.DataFrame(columns=[x_col, "series", "count"])

    out = chart_df.copy()
    if selected_lanes is not None:
        out = out[out["lane_no"].astype(str).isin([str(lane) for lane in selected_lanes])]
    if out.empty:
        return pd.DataFrame(columns=[x_col, "series", "count"])

    out = out.rename(columns={"lane_no": "series", "avg_gap_sec": "count"})
    out[x_col] = out[x_col].astype(str)
    out["series"] = out["series"].astype(str)
    out = out[out["count"].notna()].copy()

    if x_order is not None:
        categories = [str(value) for value in x_order]
        out[x_col] = pd.Categorical(out[x_col], categories=categories, ordered=True)

    lane_order = [lane for lane in LANES if lane in set(out["series"])]
    if lane_order:
        out["series"] = pd.Categorical(out["series"], categories=lane_order, ordered=True)

    return out.sort_values([x_col, "series"])


def gap_lane_vehicle_totals(chart_df: pd.DataFrame) -> dict[str, int]:
    if chart_df.empty:
        return {}
    totals = (
        chart_df.groupby("lane_no", observed=False)["vehicle_count"]
        .sum()
        .astype(int)
        .to_dict()
    )
    return {str(lane): int(count) for lane, count in totals.items()}


def gap_distribution_by_lane(
    chart_df: pd.DataFrame,
    selected_lanes: list[str] | None = None,
) -> pd.DataFrame:
    """One distribution summary row per lane for the selected period."""
    if chart_df.empty:
        return pd.DataFrame(
            columns=[
                "lane_no",
                "vehicle_count",
                "gap_count",
                "avg_gap_sec",
                "median_gap_sec",
                "p10_gap_sec",
                "p90_gap_sec",
                "min_gap_sec",
                "max_gap_sec",
            ]
        )

    out = chart_df.copy()
    if selected_lanes is not None:
        out = out[out["lane_no"].astype(str).isin([str(lane) for lane in selected_lanes])]

    rows: list[dict] = []
    for lane_no, group in out.groupby("lane_no", sort=True):
        rows.append({"lane_no": str(lane_no), **_aggregate_gap_group(group)})

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    lane_rank = {lane: index for index, lane in enumerate(LANES)}
    result["_sort"] = result["lane_no"].map(lambda lane: lane_rank.get(lane, 999))
    return result.sort_values("_sort").drop(columns="_sort").reset_index(drop=True)


def weighted_avg_gap_kpi(chart_df: pd.DataFrame, selected_lanes: list[str] | None = None) -> str:
    if chart_df.empty:
        return "—"
    subset = chart_df
    if selected_lanes is not None:
        subset = subset[subset["lane_no"].astype(str).isin([str(lane) for lane in selected_lanes])]
    avg = _weighted_mean(subset["avg_gap_sec"], subset["gap_count"])
    if avg is None:
        return "—"
    return f"{avg:.2f}s"


def gap_lane_avg_table(chart_df: pd.DataFrame, selected_lanes: list[str] | None = None) -> pd.DataFrame:
    dist = gap_distribution_by_lane(chart_df, selected_lanes)
    if dist.empty:
        return pd.DataFrame(columns=["Lane", "Avg gap (s)"])
    table = pd.DataFrame(
        {
            "Lane": dist["lane_no"],
            "Avg gap (s)": dist["avg_gap_sec"].map(lambda value: f"{value:.2f}" if pd.notna(value) else "—"),
        }
    )
    return table


def active_gap_lanes(chart_df: pd.DataFrame) -> list[str]:
    if chart_df.empty:
        return []
    present = set(chart_df.loc[chart_df["vehicle_count"] > 0, "lane_no"].astype(str))
    return [lane for lane in LANES if lane in present]


def top_gap_lanes_by_volume(chart_df: pd.DataFrame, top_n: int = DEFAULT_TOP_LANES) -> list[str]:
    totals = gap_lane_vehicle_totals(chart_df)
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    return [lane for lane, count in ranked[:top_n] if count > 0]


def gap_lt2_overlay_long_df(
    chart_df: pd.DataFrame,
    x_col: str,
    selected_lanes: list[str] | None = None,
) -> pd.DataFrame:
    """Points with gap_lt_2s_count > 0 for overlay markers (y = avg gap)."""
    columns = [x_col, "series", "count", "gap_lt_2s_count"]
    if chart_df.empty or "gap_lt_2s_count" not in chart_df.columns:
        return pd.DataFrame(columns=columns)

    out = chart_df.copy()
    if selected_lanes is not None:
        out = out[out["lane_no"].astype(str).isin([str(lane) for lane in selected_lanes])]
    out["gap_lt_2s_count"] = pd.to_numeric(out["gap_lt_2s_count"], errors="coerce").fillna(0)
    out = out[(out["gap_lt_2s_count"] > 0) & out["avg_gap_sec"].notna()].copy()
    if out.empty:
        return pd.DataFrame(columns=columns)

    out = out.rename(columns={"lane_no": "series", "avg_gap_sec": "count"})
    out[x_col] = out[x_col].astype(str)
    out["series"] = out["series"].astype(str)
    return out[columns].sort_values([x_col, "series"])


def gap_lt2_flag_table(
    chart_df: pd.DataFrame,
    x_col: str,
    selected_lanes: list[str] | None = None,
) -> pd.DataFrame:
    """Exception list: only lane×time buckets with at least one <2s gap."""
    empty = pd.DataFrame(columns=["Time", "Lane", "<2s gaps", "Avg gap (s)"])
    if chart_df.empty or "gap_lt_2s_count" not in chart_df.columns:
        return empty

    out = chart_df.copy()
    if selected_lanes is not None:
        out = out[out["lane_no"].astype(str).isin([str(lane) for lane in selected_lanes])]
    out["gap_lt_2s_count"] = pd.to_numeric(out["gap_lt_2s_count"], errors="coerce").fillna(0).astype(int)
    out = out[out["gap_lt_2s_count"] > 0].copy()
    if out.empty:
        return empty

    out["_lane_rank"] = out["lane_no"].map(lambda lane: list(LANES).index(lane) if lane in LANES else 999)
    out = out.sort_values(["gap_lt_2s_count", x_col, "_lane_rank"], ascending=[False, True, True])
    return pd.DataFrame(
        {
            "Time": out[x_col].astype(str),
            "Lane": out["lane_no"].astype(str),
            "<2s gaps": out["gap_lt_2s_count"],
            "Avg gap (s)": out["avg_gap_sec"].map(
                lambda value: f"{value:.2f}" if pd.notna(value) else "—"
            ),
        }
    ).reset_index(drop=True)


def gap_lt2_heatmap_matrix(
    chart_df: pd.DataFrame,
    x_col: str,
    x_order: list | None,
    selected_lanes: list[str] | None = None,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """
    Build lane × time matrix of <2s gap counts.
    Returns (matrix_df indexed by lane, lane_order, x_order_used).
    """
    if chart_df.empty:
        return pd.DataFrame(), [], []

    out = chart_df.copy()
    if selected_lanes is not None:
        out = out[out["lane_no"].astype(str).isin([str(lane) for lane in selected_lanes])]
    if out.empty:
        return pd.DataFrame(), [], []

    if "gap_lt_2s_count" not in out.columns:
        out["gap_lt_2s_count"] = 0
    out["gap_lt_2s_count"] = pd.to_numeric(out["gap_lt_2s_count"], errors="coerce").fillna(0)
    out[x_col] = out[x_col].astype(str)
    out["lane_no"] = out["lane_no"].astype(str)

    categories = [str(value) for value in x_order] if x_order else sorted(out[x_col].unique().tolist())
    lane_order = [lane for lane in LANES if lane in set(out["lane_no"])]
    if not lane_order:
        lane_order = sorted(out["lane_no"].unique().tolist())

    pivot = out.pivot_table(
        index="lane_no",
        columns=x_col,
        values="gap_lt_2s_count",
        aggfunc="sum",
        fill_value=0,
        observed=False,
    )
    for category in categories:
        if category not in pivot.columns:
            pivot[category] = 0
    pivot = pivot.reindex(index=lane_order, columns=categories, fill_value=0)
    return pivot, lane_order, categories
