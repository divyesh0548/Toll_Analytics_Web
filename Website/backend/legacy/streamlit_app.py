"""
NHIT Analytics Dashboard — Streamlit + Plotly (legacy).

Run from Website/backend:
    streamlit run legacy/streamlit_app.py
"""

from __future__ import annotations

import calendar
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.charts import class_bar_chart, line_series_chart
from app.utils.analytics_config import (
    LANES,
    MAX_DAY_WINDOW,
    MAX_HOUR_WINDOW,
    MIN_DAY_WINDOW,
    MIN_HOUR_WINDOW,
    MOP_TYPES,
    VEHICLE_CLASSES,
)
from app.utils.data_utils import (
    active_gap_lanes,
    active_lane_map,
    aggregate_daily_range,
    aggregate_hourly_window,
    aggregate_month_span,
    build_gap_time_series,
    format_hour_window,
    format_total_kpi,
    gap_avg_long_df,
    gap_lane_avg_table,
    gap_lane_vehicle_totals,
    gap_lt2_flag_table,
    gap_lt2_overlay_long_df,
    hour_labels_from_range,
    hour_sort_key,
    melt_metric_columns,
    melt_time_buckets_by_category,
    metric_share_pct_df,
    series_order_by_total,
    series_order_from_labels,
    top_gap_lanes_by_volume,
    top_lanes_by_volume,
    weighted_avg_gap_kpi,
)
from app.services.analytics_db import (
    fetch_analytics,
    fetch_exempt_distribution,
    fetch_gap_distribution,
    fetch_plaza_names,
)

st.set_page_config(
    page_title="NHIT Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

TIME_MODES = ("Hours", "Day on day", "Month")
VIEW_VOLUME = "Vehicle class & Lane distribution"
VIEW_CLASS_MIX = "Class Mix"
VIEW_MOP = "MOP Distribution"
VIEW_GAP = "Gap Distribution"
VIEW_EXEMPT = "Exempt Distribution"
DASHBOARD_VIEWS = (VIEW_VOLUME, VIEW_CLASS_MIX, VIEW_MOP, VIEW_GAP, VIEW_EXEMPT)

AXIS_CONFIG = {
    "Hours": {"x_axis_title": "Hour", "hover_bucket_label": "Hour"},
    "Day on day": {"x_axis_title": "Date", "hover_bucket_label": "Date"},
    "Month": {"x_axis_title": "Date", "hover_bucket_label": "Date"},
}


VOLUME_CLASS_X_AXIS_OPTIONS = ("Time", "Vehicle class")
VOLUME_LANE_X_AXIS_OPTIONS = ("Time", "Lanes")
DEFAULT_HOUR_RANGE = (0, 12)
CONTROL_MIN_WIDTH = "180px"
SLIDER_MIN_WIDTH = "260px"
DAY_TICK_DENSITY_LIMIT = 25
COMPACT_DAY_TICK_DENSITY_LIMIT = 16
PLOTLY_CHART_CONFIG = {
    "scrollZoom": False,
    "displayModeBar": False,
    "responsive": True,
    "doubleClick": False,
    "modeBarButtonsToRemove": [
        "zoom2d",
        "pan2d",
        "select2d",
        "lasso2d",
        "autoScale2d",
        "resetScale2d",
    ],
}


def render_plotly_chart(figure) -> None:
    st.plotly_chart(
        figure,
        width="stretch",
        height="content",
        config=PLOTLY_CHART_CONFIG,
    )


def apply_compact_control_styles() -> None:
    st.markdown(
        f"""
        <style>
        .block-container {{
            padding-top: 1.6rem;
        }}
        h1 {{
            letter-spacing: 0;
            margin-bottom: 0.15rem;
        }}
        h3 {{
            margin-top: 1.35rem;
            margin-bottom: 0.35rem;
            letter-spacing: 0;
        }}
        div[data-testid="stTabs"] {{
            margin-top: 0;
        }}
        div[data-testid="stTabs"] [data-baseweb="tab-border"] {{
            display: none !important;
        }}
        div[data-testid="stTabs"] button {{
            padding-top: 0.8rem;
            padding-bottom: 0.8rem;
        }}
        div[class*="lane_chart_controls"],
        div[class*="gap_lane_controls"],
        div[class*="mop_chart_controls"],
        div[class*="exempt_lane_controls"] {{
            width: 100% !important;
            max-width: 100% !important;
        }}
        div[class*="lane_chart_controls"] div[data-testid="stHorizontalBlock"],
        div[class*="gap_lane_controls"] div[data-testid="stHorizontalBlock"],
        div[class*="mop_chart_controls"] div[data-testid="stHorizontalBlock"],
        div[class*="exempt_lane_controls"] div[data-testid="stHorizontalBlock"] {{
            width: fit-content !important;
            max-width: 100% !important;
            align-items: center !important;
            column-gap: clamp(1rem, 2.5vw, 2rem) !important;
            flex-wrap: nowrap !important;
        }}
        div[class*="lane_chart_controls"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
        div[class*="gap_lane_controls"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
        div[class*="mop_chart_controls"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
        div[class*="exempt_lane_controls"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {{
            flex: 0 0 auto !important;
            width: auto !important;
            min-width: max-content !important;
            padding: 0 !important;
        }}
        div[class*="lane_chart_controls"] div[data-testid="stSelectbox"] > div {{
            width: clamp(12rem, 22vw, 18rem) !important;
            min-width: 0 !important;
            max-width: 100% !important;
        }}
        div[class*="class_chart_controls"] {{
            width: 100% !important;
            max-width: 100% !important;
        }}
        div[class*="class_chart_controls"] div[data-testid="stSelectbox"] > div {{
            width: clamp(12rem, 22vw, 18rem) !important;
            min-width: 0 !important;
            max-width: 100% !important;
        }}
        div[class*="lane_chart_controls"] div[data-testid="stCheckbox"],
        div[class*="lane_chart_controls"] div[data-testid="stToggle"],
        div[class*="gap_lane_controls"] div[data-testid="stCheckbox"],
        div[class*="gap_lane_controls"] div[data-testid="stToggle"],
        div[class*="mop_chart_controls"] div[data-testid="stCheckbox"],
        div[class*="mop_chart_controls"] div[data-testid="stToggle"],
        div[class*="exempt_lane_controls"] div[data-testid="stCheckbox"],
        div[class*="exempt_lane_controls"] div[data-testid="stToggle"] {{
            min-width: max-content !important;
            margin-bottom: 0 !important;
        }}
        div[class*="_time_controls"] {{
            border-bottom: 1px solid rgba(128, 128, 128, 0.35);
            padding-bottom: 0.85rem;
            margin-bottom: 1.25rem;
        }}
        div[data-testid="stPlotlyChart"],
        div[data-testid="stPlotlyChart"] > div,
        div[data-testid="stPlotlyChart"] iframe,
        div[data-testid="stElementContainer"]:has([data-testid="stPlotlyChart"]),
        [data-testid="stVerticalBlockBorderWrapper"]:has([data-testid="stPlotlyChart"]) {{
            overflow: hidden !important;
            overflow-x: hidden !important;
            overflow-y: hidden !important;
            scrollbar-width: none !important;
        }}
        div[data-testid="stPlotlyChart"]::-webkit-scrollbar,
        div[data-testid="stPlotlyChart"] > div::-webkit-scrollbar,
        div[data-testid="stElementContainer"]:has([data-testid="stPlotlyChart"])::-webkit-scrollbar {{
            display: none !important;
            width: 0 !important;
            height: 0 !important;
        }}
        div[data-testid="stPlotlyChart"] {{
            overscroll-behavior: none !important;
            max-height: none !important;
            touch-action: pan-y !important;
        }}
        div[data-testid="stSelectbox"] > div,
        div[data-testid="stDateInput"] > div {{
            width: 100%;
            min-width: {CONTROL_MIN_WIDTH};
            max-width: 100%;
        }}
        div[data-testid="stSlider"] {{
            width: 100%;
            min-width: {SLIDER_MIN_WIDTH};
            max-width: 100%;
            padding-top: 0.15rem;
        }}
        div[data-testid="stWidgetLabel"] {{
            margin-bottom: 0.2rem;
        }}
        /* Native toggle/checkbox: keep switch and text on one baseline. */
        div[data-testid="stToggle"] [data-testid="stWidgetLabel"],
        div[data-testid="stCheckbox"] [data-testid="stWidgetLabel"] {{
            margin: 0 !important;
            padding: 0 !important;
        }}
        div[data-testid="stToggle"] label,
        div[data-testid="stCheckbox"] label {{
            align-items: center !important;
            gap: 0.5rem !important;
            margin-bottom: 0 !important;
        }}
        div[data-testid="stToggle"] [data-testid="stWidgetLabel"] p,
        div[data-testid="stCheckbox"] [data-testid="stWidgetLabel"] p {{
            margin: 0 !important;
            line-height: 1.25 !important;
            padding-top: 0 !important;
        }}
        div[data-testid="stToggle"] [data-testid="stTooltipHoverTarget"],
        div[data-testid="stCheckbox"] [data-testid="stTooltipHoverTarget"],
        div[data-testid="stToggle"] [data-testid="stTooltipIcon"],
        div[data-testid="stCheckbox"] [data-testid="stTooltipIcon"] {{
            display: inline-flex !important;
            align-items: center !important;
            vertical-align: middle !important;
        }}
        div[class*="lane_chart_controls"] [data-testid="stElementContainer"]:has([data-testid="stToggle"]),
        div[class*="gap_lane_controls"] [data-testid="stElementContainer"]:has([data-testid="stToggle"]),
        div[class*="mop_chart_controls"] [data-testid="stElementContainer"]:has([data-testid="stToggle"]),
        div[class*="exempt_lane_controls"] [data-testid="stElementContainer"]:has([data-testid="stToggle"]),
        div[class*="_time_controls"] [data-testid="stElementContainer"]:has([data-testid="stToggle"]) {{
            margin-bottom: 0 !important;
            align-items: center !important;
        }}
        div[data-testid="stWidgetLabel"] label {{
            font-weight: 600;
            line-height: 1.2;
        }}
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div {{
            border-radius: 6px;
            min-height: 40px;
            box-shadow: none;
        }}
        div[data-testid="stPlotlyChart"] {{
            margin-top: 0.15rem;
        }}
        div[class*="_category_selector"] {{
            margin-top: 0.15rem;
            margin-bottom: 0.35rem;
        }}
        div[class*="_category_selector"] div[data-testid="stCaptionContainer"] {{
            margin-bottom: 0.2rem !important;
        }}
        div[class*="_category_selector"] div[data-testid="stPills"] {{
            margin-top: 0 !important;
            margin-bottom: 0.15rem !important;
        }}
        div[class*="_category_selector"] div[data-testid="stPills"] > div {{
            gap: 0.3rem !important;
            row-gap: 0.3rem !important;
            flex-wrap: wrap !important;
        }}
        div[class*="_category_selector"] div[data-testid="stPills"] button {{
            min-height: 1.7rem !important;
            padding: 0.15rem 0.55rem !important;
            font-size: 0.88rem !important;
            line-height: 1.2 !important;
            border-radius: 999px !important;
        }}
        @media (max-width: 768px) {{
            div[data-testid="stSelectbox"] > div,
            div[data-testid="stDateInput"] > div,
            div[data-testid="stSlider"] {{
                max-width: 100%;
                min-width: 0;
            }}
            div[class*="lane_chart_controls"] div[data-testid="stHorizontalBlock"] {{
                width: 100% !important;
                flex-wrap: wrap !important;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


SECTION_KEY_TO_VIEW = {
    "volume": VIEW_VOLUME,
    "class_mix": VIEW_CLASS_MIX,
    "mop": VIEW_MOP,
    "gap": VIEW_GAP,
    "exempt": VIEW_EXEMPT,
}

def mark_dashboard_view(view: str) -> None:
    st.session_state["dashboard_kpi_source"] = view


def mark_dashboard_view_for_section(section_key: str) -> None:
    view = SECTION_KEY_TO_VIEW.get(section_key)
    if view:
        mark_dashboard_view(view)


def section_date_input(section_key: str, label: str, *, key: str, **kwargs) -> date:
    return st.date_input(
        label,
        key=key,
        on_change=mark_dashboard_view_for_section,
        args=(section_key,),
        **kwargs,
    )


def section_selectbox(section_key: str, label: str, *, key: str, **kwargs):
    return st.selectbox(
        label,
        key=key,
        on_change=mark_dashboard_view_for_section,
        args=(section_key,),
        **kwargs,
    )


def filter_df_by_params(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    mode = params["mode"]
    if mode == "Hours":
        return df[(df["date"] == params["selected_date"]) & (df["hour"].isin(params["hour_labels"]))]
    if mode == "Day on day":
        return df[(df["date"] >= params["start_date"]) & (df["date"] <= params["end_date"])]
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
    return df[combined]


def year_month_key(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def parse_year_month_key(value: str) -> tuple[int, int]:
    year_text, month_text = str(value).split("-", 1)
    return int(year_text), int(month_text)


def format_year_month_key(value: str) -> str:
    year, month = parse_year_month_key(value)
    return f"{calendar.month_name[month]} {year}"


def available_year_month_keys(dates: list[date]) -> list[str]:
    return [year_month_key(year, month) for year, month in sorted({(value.year, value.month) for value in dates})]


def build_params_from_session(section_key: str, dates: list[date]) -> dict | None:
    mode_key = f"{section_key}_mode"
    if mode_key not in st.session_state:
        return None

    mode = st.session_state[mode_key]
    params: dict = {"mode": mode}
    flexible_hours = section_key in {"volume", "gap", "exempt"}

    if mode == "Hours":
        date_key = f"{section_key}_hour_date"
        range_key = f"{section_key}_hour_range"
        if date_key not in st.session_state or range_key not in st.session_state:
            return None
        start_hour, end_hour = st.session_state[range_key]
        hour_labels = hour_labels_from_range(start_hour, end_hour)
        hour_valid, _ = validate_hour_range(start_hour, end_hour, enforce_max=not flexible_hours)
        if not hour_valid:
            return None
        params["selected_date"] = st.session_state[date_key]
        params["start_hour"] = start_hour
        params["hour_labels"] = hour_labels
        return params

    if mode == "Day on day":
        start_key = f"{section_key}_daily_start"
        end_key = f"{section_key}_daily_end"
        if start_key not in st.session_state or end_key not in st.session_state:
            return None
        params["start_date"] = st.session_state[start_key]
        params["end_date"] = st.session_state[end_key]
        day_valid, _ = validate_day_range(params["start_date"], params["end_date"])
        if not day_valid:
            return None
        return params

    months_key = f"{section_key}_year_months"
    if months_key not in st.session_state:
        # Backward compat with older single year/month widgets.
        year_key = f"{section_key}_year"
        month_key = f"{section_key}_month"
        if year_key in st.session_state and month_key in st.session_state:
            params["year_months"] = [(st.session_state[year_key], st.session_state[month_key])]
            params["year"] = st.session_state[year_key]
            params["month"] = st.session_state[month_key]
            return params
        return None

    selected_keys = st.session_state[months_key] or []
    if not selected_keys:
        return None
    year_months = sorted(parse_year_month_key(value) for value in selected_keys)
    params["year_months"] = year_months
    params["year"] = year_months[0][0]
    params["month"] = year_months[0][1]
    return params


def resolve_active_dashboard_view() -> str:
    """Sync KPI source from Streamlit tab state when available."""
    views = list(DASHBOARD_VIEWS)
    for key, value in st.session_state.items():
        if not isinstance(key, str) or "tab" not in key.lower():
            continue
        if isinstance(value, int) and 0 <= value < len(views):
            st.session_state["dashboard_kpi_source"] = views[value]
            return views[value]
        if isinstance(value, str) and value in views:
            st.session_state["dashboard_kpi_source"] = value
            return value
    return st.session_state.get("dashboard_kpi_source", VIEW_VOLUME)


def compute_section_kpi(df: pd.DataFrame, view: str) -> tuple[str, str] | None:
    if df.empty and view not in {VIEW_GAP, VIEW_EXEMPT}:
        return None

    section_key = {
        VIEW_VOLUME: "volume",
        VIEW_CLASS_MIX: "class_mix",
        VIEW_MOP: "mop",
        VIEW_GAP: "gap",
        VIEW_EXEMPT: "exempt",
    }.get(view)
    if not section_key:
        return None

    if view == VIEW_GAP:
        gap_df = st.session_state.get("gap_df", pd.DataFrame())
        if gap_df is None or gap_df.empty:
            return ("Avg gap", "—")
        dates = available_dates(gap_df)
        if not dates:
            return ("Avg gap", "—")
        params = build_params_from_session(section_key, dates)
        if not params:
            return ("Avg gap", "—")
        chart_df, _, _, _, _ = build_gap_time_series(gap_df, params)
        return ("Avg gap", weighted_avg_gap_kpi(chart_df))

    if view == VIEW_EXEMPT:
        exempt_df = st.session_state.get("exempt_df", pd.DataFrame())
        if exempt_df is None or exempt_df.empty:
            return ("Exempt vehicles", "—")
        dates = available_dates(exempt_df)
        if not dates:
            return ("Exempt vehicles", "—")
        params = build_params_from_session(section_key, dates)
        if not params:
            return ("Exempt vehicles", "—")
        chart_df, _, _, _, _ = build_time_series_df(exempt_df, params)
        return ("Exempt vehicles", format_total_kpi(chart_df))

    if df.empty:
        return None

    dates = available_dates(df)
    if not dates:
        return None

    params = build_params_from_session(section_key, dates)
    if not params:
        return None

    if view == VIEW_CLASS_MIX:
        filtered = filter_df_by_params(df, params)
        return ("Total vehicles", format_total_kpi(filtered))

    chart_df, _, _, _, _ = build_time_series_df(df, params)
    label = "Total transactions" if view == VIEW_MOP else "Total vehicles"
    return (label, format_total_kpi(chart_df))


def render_dashboard_title() -> st.delta_generator.DeltaGenerator:
    title_col, total_col = st.columns([4, 2], vertical_alignment="center")
    with title_col:
        st.title("Toll Analytics Dashboard For InvITs")
        st.caption(
            "Traffic volume, vehicle class mix, mode-of-payment, lane gap, and exempt trends."
        )
    return total_col.empty()


def render_dashboard_kpi(kpi_slot: st.delta_generator.DeltaGenerator, label: str, total: str) -> None:
    with kpi_slot.container():
        st.markdown(
            f"""
            <div class="dashboard-kpi" style="text-align: right; white-space: nowrap; line-height: 1.3;">
                <span style="color: #6b7280; font-size: 0.95rem;">{label}:</span>
                <span style="font-size: 1.35rem; font-weight: 600; margin-left: 0.35rem;">{total}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_chart_section_header(section_title: str) -> None:
    st.subheader(section_title)


def category_checkbox_key(chart_key: str, category: str) -> str:
    return f"{chart_key}_cat_{category}"


def section_key_from_chart_key(chart_key: str) -> str:
    if chart_key.startswith("volume"):
        return "volume"
    if chart_key.startswith("gap"):
        return "gap"
    if chart_key.startswith("mop"):
        return "mop"
    if chart_key.startswith("class"):
        return "class_mix"
    return chart_key


def render_category_selector(chart_key: str, category_options: list[str]) -> list[str]:
    options = [str(category) for category in category_options]
    if not options:
        return []

    options_key = f"{chart_key}_category_options"
    pills_key = f"{chart_key}_category_pills"
    if st.session_state.get(options_key) != options:
        st.session_state[options_key] = options
        st.session_state[pills_key] = options

    if pills_key not in st.session_state:
        # Prefer prior checkbox selections when migrating from the old control.
        prior = [
            category
            for category in options
            if st.session_state.get(category_checkbox_key(chart_key, category), True)
        ]
        st.session_state[pills_key] = prior or options

    with st.container(key=f"{chart_key}_category_selector"):
        selected = st.pills(
            "Visible categories",
            options=options,
            selection_mode="multi",
            key=pills_key,
            on_change=mark_dashboard_view_for_section,
            args=(section_key_from_chart_key(chart_key),),
        )

    if not selected:
        return []
    selected_set = {str(value) for value in selected}
    return [category for category in options if category in selected_set]


def format_period_label(params: dict) -> str:
    mode = params["mode"]
    if mode == "Hours":
        return f"{params['selected_date']} · {format_hour_window(params['hour_labels'])}"
    if mode == "Day on day":
        return f"{params['start_date']} – {params['end_date']}"
    year_months = params.get("year_months") or [(params["year"], params["month"])]
    labels = [f"{calendar.month_abbr[month]} {year}" for year, month in year_months]
    return ", ".join(labels)


def default_comparison_date(dates: list[date], primary_date: date) -> date:
    alternatives = [value for value in dates if value > primary_date]
    return alternatives[0] if alternatives else dates[0]


def default_comparison_day_range(
    dates: list[date],
    primary_start: date,
    primary_end: date,
) -> tuple[date, date]:
    primary_days = (primary_end - primary_start).days + 1
    window = min(max(primary_days, MIN_DAY_WINDOW), MAX_DAY_WINDOW)
    next_start = primary_end + timedelta(days=1)
    next_end = next_start + timedelta(days=window - 1)
    if next_end <= dates[-1]:
        return next_start, next_end

    fallback_end = dates[-1]
    fallback_start = max(dates[0], fallback_end - timedelta(days=window - 1))
    return fallback_start, fallback_end


def default_comparison_year_month(
    dates: list[date],
    primary_year: int,
    primary_month: int,
) -> tuple[int, int]:
    year_months = default_comparison_year_months(dates, [(primary_year, primary_month)])
    return year_months[0]


def default_comparison_year_months(
    dates: list[date],
    primary_year_months: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    available = sorted({(value.year, value.month) for value in dates})
    primary = sorted(primary_year_months) or [available[0]]
    count = len(primary)
    last_primary = primary[-1]
    start_index = next((index + 1 for index, pair in enumerate(available) if pair == last_primary), None)
    if start_index is not None and start_index < len(available):
        selected = available[start_index : start_index + count]
        if len(selected) == count:
            return selected
    # Fallback: earliest contiguous block of the same length.
    if len(available) >= count:
        return available[:count]
    return available


def initialize_comparison_period(
    section_key: str,
    dates: list[date],
) -> None:
    """Seed comparison widgets with the next period when comparison is enabled."""
    mark_dashboard_view_for_section(section_key)
    if not st.session_state.get(f"{section_key}_compare"):
        return

    primary_params = build_params_from_session(section_key, dates)
    if not primary_params:
        return

    mode = primary_params["mode"]
    if mode == "Hours":
        start_hour = primary_params["start_hour"]
        end_hour = start_hour + len(primary_params["hour_labels"])
        st.session_state[f"{section_key}_cmp_hour_date"] = default_comparison_date(
            dates,
            primary_params["selected_date"],
        )
        st.session_state[f"{section_key}_cmp_hour_range"] = (start_hour, end_hour)
        return

    if mode == "Day on day":
        start_date, end_date = default_comparison_day_range(
            dates,
            primary_params["start_date"],
            primary_params["end_date"],
        )
        st.session_state[f"{section_key}_cmp_daily_start"] = start_date
        st.session_state[f"{section_key}_cmp_daily_end"] = end_date
        return

    year_months = primary_params.get("year_months") or [
        (primary_params["year"], primary_params["month"])
    ]
    compare_months = default_comparison_year_months(dates, year_months)
    st.session_state[f"{section_key}_cmp_year_months"] = [
        year_month_key(year, month) for year, month in compare_months
    ]


def filter_long_df_series(long_df: pd.DataFrame, selected_categories: list[str]) -> pd.DataFrame:
    if long_df.empty:
        return long_df
    if not selected_categories:
        return long_df.iloc[0:0].copy()
    selected = {str(value) for value in selected_categories}
    return long_df[long_df["series"].astype(str).isin(selected)].copy()


def filter_long_df_x_values(
    long_df: pd.DataFrame,
    x_col: str,
    selected_categories: list[str],
) -> pd.DataFrame:
    if long_df.empty:
        return long_df
    if not selected_categories:
        return long_df.iloc[0:0].copy()
    selected = {str(value) for value in selected_categories}
    return long_df[long_df[x_col].astype(str).isin(selected)].copy()


def category_totals(chart_df: pd.DataFrame, column_map: dict[str, str]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for label, col in column_map.items():
        if col in chart_df.columns:
            totals[str(label)] = int(pd.to_numeric(chart_df[col], errors="coerce").fillna(0).sum())
    return totals


def category_share_table(chart_df: pd.DataFrame, column_map: dict[str, str]) -> pd.DataFrame:
    """Overall count and % share for each category in the selected period."""
    totals = category_totals(chart_df, column_map)
    grand_total = sum(totals.values())
    rows = []
    for label in column_map:
        count = totals.get(str(label), 0)
        share = (count / grand_total * 100.0) if grand_total else 0.0
        rows.append(
            {
                "Category": str(label),
                "Count": count,
                "Share (%)": round(share, 1),
            }
        )
    return pd.DataFrame(rows)


def format_chart_total(chart_df: pd.DataFrame, column_map: dict[str, str]) -> str:
    return f"{sum(category_totals(chart_df, column_map).values()):,}"


def day_x_tick_stride(time_mode: str, x_order: list | None, *, compact: bool) -> int:
    if time_mode != "Day on day" or not x_order:
        return 1
    density_limit = COMPACT_DAY_TICK_DENSITY_LIMIT if compact else DAY_TICK_DENSITY_LIMIT
    return 2 if len(x_order) > density_limit else 1


def build_line_chart_figure(
    chart_df: pd.DataFrame,
    column_map: dict[str, str],
    *,
    params: dict,
    time_mode: str,
    x_col: str,
    x_order: list | None,
    highlight_days: bool,
    categories_on_x_axis: bool,
    legend_mode: str,
    fixed_legend_order: list[str] | None,
    selected_categories: list[str],
    title: str,
    x_axis_title: str,
    hover_bucket_label: str,
    period_label: str,
    y_title: str = "Vehicle count",
    compact: bool = False,
    value_suffix: str = "",
    as_percent: bool = False,
):
    # Keep legend order from absolute counts when drawing % share lines.
    effective_legend_mode = legend_mode
    effective_fixed_order = fixed_legend_order
    if as_percent and legend_mode == "total" and not categories_on_x_axis:
        abs_long = melt_metric_columns(chart_df, x_col, column_map, x_order)
        effective_fixed_order = series_order_by_total(abs_long)
        effective_legend_mode = "fixed"

    plot_df = metric_share_pct_df(chart_df, column_map) if as_percent else chart_df
    long_df, plot_x_col, plot_x_order, series_order = build_volume_chart_data(
        plot_df,
        column_map,
        categories_on_x_axis=categories_on_x_axis,
        time_mode=time_mode,
        params=params,
        x_col=x_col,
        x_order=x_order,
        legend_mode=effective_legend_mode,
        fixed_legend_order=effective_fixed_order,
    )
    # Legend totals stay absolute counts even when the line is drawn as %.
    totals = category_totals(chart_df, column_map)
    series_totals = totals
    x_value_totals = None

    if categories_on_x_axis:
        long_df = filter_long_df_x_values(long_df, plot_x_col, selected_categories)
        if plot_x_order:
            plot_x_order = [value for value in plot_x_order if str(value) in selected_categories]
        series_totals = None
        x_value_totals = totals
    else:
        long_df = filter_long_df_series(long_df, selected_categories)
        if series_order:
            series_order = [value for value in series_order if value in selected_categories]

    x_tick_stride = day_x_tick_stride(
        time_mode,
        plot_x_order,
        compact=compact,
    ) if not categories_on_x_axis else 1

    return line_series_chart(
        long_df,
        plot_x_col,
        f"{title} — {period_label}",
        y_title=y_title,
        x_axis_title=x_axis_title,
        hover_bucket_label=hover_bucket_label,
        x_order=plot_x_order,
        series_order=series_order,
        highlight_every_nth_day=5 if highlight_days and not categories_on_x_axis else None,
        compact=compact,
        series_totals=series_totals,
        x_value_totals=x_value_totals,
        x_tick_stride=x_tick_stride,
        value_suffix=value_suffix,
    )


def render_comparable_line_chart(
    chart_key: str,
    df: pd.DataFrame,
    column_map: dict[str, str],
    primary_params: dict,
    *,
    time_mode: str,
    chart_df: pd.DataFrame,
    x_col: str,
    x_order: list | None,
    highlight_days: bool,
    categories_on_x_axis: bool,
    legend_mode: str,
    fixed_legend_order: list[str] | None,
    title: str,
    x_axis_title: str,
    hover_bucket_label: str,
    compare_enabled: bool,
    comparison_params: dict | None,
    y_title: str = "Vehicle count",
    total_label: str = "Total vehicles",
    selected_categories: list[str] | None = None,
    as_percent: bool = False,
    value_suffix: str = "",
) -> list[str]:
    category_options = list(fixed_legend_order or column_map.keys())
    if selected_categories is None:
        selected_categories = render_category_selector(chart_key, category_options)
    if not selected_categories:
        selected_categories = category_options

    primary_label = format_period_label(primary_params)

    if not compare_enabled:
        render_plotly_chart(
            build_line_chart_figure(
                chart_df,
                column_map,
                params=primary_params,
                time_mode=time_mode,
                x_col=x_col,
                x_order=x_order,
                highlight_days=highlight_days,
                categories_on_x_axis=categories_on_x_axis,
                legend_mode=legend_mode,
                fixed_legend_order=fixed_legend_order,
                selected_categories=selected_categories,
                title=title,
                x_axis_title=x_axis_title,
                hover_bucket_label=hover_bucket_label,
                period_label=primary_label,
                y_title=y_title,
                compact=False,
                as_percent=as_percent,
                value_suffix=value_suffix,
            ),
        )
        return selected_categories

    if comparison_params is None:
        return selected_categories

    left_col, right_col = st.columns(2, gap="small")
    with left_col:
        st.metric(total_label, format_chart_total(chart_df, column_map))
        render_plotly_chart(
            build_line_chart_figure(
                chart_df,
                column_map,
                params=primary_params,
                time_mode=time_mode,
                x_col=x_col,
                x_order=x_order,
                highlight_days=highlight_days,
                categories_on_x_axis=categories_on_x_axis,
                legend_mode=legend_mode,
                fixed_legend_order=fixed_legend_order,
                selected_categories=selected_categories,
                title=title,
                x_axis_title=x_axis_title,
                hover_bucket_label=hover_bucket_label,
                period_label=primary_label,
                y_title=y_title,
                compact=True,
                as_percent=as_percent,
                value_suffix=value_suffix,
            ),
        )

    with right_col:
        compare_chart_df, compare_x_col, compare_x_order, compare_highlight_days, _ = build_time_series_df(
            df,
            comparison_params,
        )
        compare_label = format_period_label(comparison_params)
        st.metric(total_label, format_chart_total(compare_chart_df, column_map))
        render_plotly_chart(
            build_line_chart_figure(
                compare_chart_df,
                column_map,
                params=comparison_params,
                time_mode=time_mode,
                x_col=compare_x_col,
                x_order=compare_x_order,
                highlight_days=compare_highlight_days,
                categories_on_x_axis=categories_on_x_axis,
                legend_mode=legend_mode,
                fixed_legend_order=fixed_legend_order,
                selected_categories=selected_categories,
                title=title,
                x_axis_title=x_axis_title,
                hover_bucket_label=hover_bucket_label,
                period_label=compare_label,
                y_title=y_title,
                compact=True,
                as_percent=as_percent,
                value_suffix=value_suffix,
            ),
        )

    return selected_categories


def chart_axis_config(mode: str) -> dict[str, str]:
    return AXIS_CONFIG.get(mode, {"x_axis_title": "Time", "hover_bucket_label": "Time"})


def volume_chart_title(chart_kind: str, time_mode: str, x_axis_dim: str) -> str:
    metric = "Vehicle" if chart_kind == "class" else "Lane"
    if chart_kind == "class" and x_axis_dim == "Vehicle class":
        return f"{metric} count by vehicle class"
    if chart_kind == "lane" and x_axis_dim == "Lanes":
        return f"{metric} count by lanes"

    x_label_by_mode = {
        "Hours": "hours",
        "Day on day": "day on day",
        "Month": "month",
    }
    return f"{metric} count by {x_label_by_mode.get(time_mode, 'time')}"


def volume_x_axis_title(chart_kind: str, time_mode: str, x_axis_dim: str) -> str:
    if chart_kind == "class" and x_axis_dim == "Vehicle class":
        return "Vehicle class"
    if chart_kind == "lane" and x_axis_dim == "Lanes":
        return "Lane"
    return chart_axis_config(time_mode)["x_axis_title"]


def mop_chart_title(time_mode: str, *, as_percent: bool = False) -> str:
    x_label_by_mode = {
        "Hours": "hours",
        "Day on day": "day on day",
        "Month": "month",
    }
    metric = "MOP share (%)" if as_percent else "MOP count"
    return f"{metric} by {x_label_by_mode.get(time_mode, 'time')}"


def render_mop_share_table(chart_df: pd.DataFrame, *, caption: str | None = None) -> None:
    table = category_share_table(chart_df, MOP_TYPES)
    if table.empty:
        return
    st.caption(caption or "Category share for selected period")
    st.dataframe(table, hide_index=True, width="content")


@st.cache_data(ttl=300)
def load_data(plaza_name: str) -> pd.DataFrame:
    return fetch_analytics(plaza_name=plaza_name)


@st.cache_data(ttl=300)
def load_gap_data(plaza_name: str) -> pd.DataFrame:
    return fetch_gap_distribution(plaza_name=plaza_name)


@st.cache_data(ttl=300)
def load_exempt_data(plaza_name: str) -> pd.DataFrame:
    return fetch_exempt_distribution(plaza_name=plaza_name)


def available_dates(df: pd.DataFrame) -> list[date]:
    if df.empty:
        return []
    return sorted(df["date"].unique())


def earliest_date(dates: list[date]) -> date:
    return dates[0]


def random_available_date(dates: list[date]) -> date:
    return random.choice(dates)


def default_day_on_day_range(dates: list[date]) -> tuple[date, date]:
    """Earliest available start with the minimum required window."""
    start = earliest_date(dates)
    end = dates[-1]
    for candidate in dates:
        if (candidate - start).days + 1 >= MIN_DAY_WINDOW:
            end = candidate
            break
    return start, end


def random_day_on_day_range(dates: list[date]) -> tuple[date, date]:
    """Random chronological start/end within the allowed day window."""
    candidates: list[tuple[date, date]] = []
    for index, start in enumerate(dates):
        for end in dates[index:]:
            day_count = (end - start).days + 1
            if MIN_DAY_WINDOW <= day_count <= MAX_DAY_WINDOW:
                candidates.append((start, end))
    if not candidates:
        return default_day_on_day_range(dates)
    return random.choice(candidates)


def default_year_month(dates: list[date]) -> tuple[int, int]:
    earliest = earliest_date(dates)
    return earliest.year, earliest.month


def random_year_month(dates: list[date]) -> tuple[int, int]:
    pairs = sorted({(value.year, value.month) for value in dates})
    return random.choice(pairs)


def random_year_months(dates: list[date]) -> list[tuple[int, int]]:
    return [random_year_month(dates)]


def validate_day_range(start_date: date, end_date: date) -> tuple[bool, str | None]:
    if start_date > end_date:
        return False, "Start date cannot be later than end date."
    day_count = (end_date - start_date).days + 1
    if day_count < MIN_DAY_WINDOW:
        return False, f"Select at least {MIN_DAY_WINDOW} days (currently {day_count})."
    if day_count > MAX_DAY_WINDOW:
        return False, f"Select at most {MAX_DAY_WINDOW} days (currently {day_count})."
    return True, None


def enforce_day_order(start_key: str, end_key: str) -> None:
    """Keep session start/end chronological if the user moved one past the other."""
    start_date = st.session_state.get(start_key)
    end_date = st.session_state.get(end_key)
    if start_date is None or end_date is None:
        return
    if start_date > end_date:
        st.session_state[end_key] = start_date


def validate_hour_range(start_hour: int, end_hour: int, *, enforce_max: bool = True) -> tuple[bool, str | None]:
    hour_count = end_hour - start_hour
    if hour_count < MIN_HOUR_WINDOW:
        return False, f"Select at least {MIN_HOUR_WINDOW} hours (currently {hour_count})."
    if enforce_max and hour_count > MAX_HOUR_WINDOW:
        return False, f"Select at most {MAX_HOUR_WINDOW} hours (currently {hour_count})."
    return True, None


def render_hour_range_slider(
    section_key: str,
    *,
    enforce_max: bool = True,
    key_prefix: str | None = None,
    default_range: tuple[int, int] = DEFAULT_HOUR_RANGE,
) -> tuple[int, list[str], bool]:
    widget_key = key_prefix or section_key
    hour_range = st.slider(
        "Hour range",
        min_value=0,
        max_value=24,
        value=default_range,
        key=f"{widget_key}_hour_range",
        on_change=mark_dashboard_view_for_section,
        args=(section_key,),
    )
    start_hour, end_hour = hour_range
    hour_labels = hour_labels_from_range(start_hour, end_hour)
    if hour_labels:
        st.caption(f"Selected: {format_hour_window(hour_labels)}")
    is_valid, error_message = validate_hour_range(start_hour, end_hour, enforce_max=enforce_max)
    if not is_valid:
        st.error(error_message)
    return start_hour, hour_labels, is_valid


def render_time_mode_radio(section_key: str) -> str:
    return st.radio(
        "Time granularity",
        TIME_MODES,
        horizontal=True,
        key=f"{section_key}_mode",
        on_change=mark_dashboard_view_for_section,
        args=(section_key,),
    )


def render_period_controls(
    section_key: str,
    dates: list[date],
    mode: str,
    *,
    state_key: str | None = None,
    flexible_hour_window: bool = False,
    comparison: bool = False,
    primary_params: dict | None = None,
) -> tuple[dict, bool]:
    """Render one primary or comparison period using the same control layout."""
    state_key = state_key or section_key
    params: dict = {"mode": mode}

    if mode == "Hours":
        default_date = random_available_date(dates)
        default_range = DEFAULT_HOUR_RANGE
        if comparison and primary_params:
            default_date = default_comparison_date(dates, primary_params["selected_date"])
            primary_start = primary_params["start_hour"]
            primary_end = primary_start + len(primary_params["hour_labels"])
            default_range = (primary_start, primary_end)
        date_key = f"{state_key}_hour_date"
        range_key = f"{state_key}_hour_range"
        st.session_state.setdefault(date_key, default_date)
        st.session_state.setdefault(range_key, default_range)
        col1, col2 = st.columns([1, 1.65], gap="small")
        with col1:
            params["selected_date"] = section_date_input(
                section_key,
                "Date",
                value=st.session_state[date_key],
                min_value=dates[0],
                max_value=dates[-1],
                key=date_key,
            )
        with col2:
            start_hour, hour_labels, hour_valid = render_hour_range_slider(
                section_key,
                key_prefix=state_key,
                enforce_max=flexible_hour_window,
                default_range=default_range,
            )
            params["start_hour"] = start_hour
            params["hour_labels"] = hour_labels
            params["hour_range_valid"] = hour_valid
        return params, hour_valid

    if mode == "Day on day":
        if comparison and primary_params:
            default_start, default_end = default_comparison_day_range(
                dates,
                primary_params["start_date"],
                primary_params["end_date"],
            )
        else:
            default_start, default_end = random_day_on_day_range(dates)
        start_key = f"{state_key}_daily_start"
        end_key = f"{state_key}_daily_end"
        st.session_state.setdefault(start_key, default_start)
        st.session_state.setdefault(end_key, default_end)
        enforce_day_order(start_key, end_key)
        col1, col2 = st.columns(2, gap="small")
        with col1:
            params["start_date"] = section_date_input(
                section_key,
                "Start date",
                value=st.session_state[start_key],
                min_value=dates[0],
                max_value=min(st.session_state[end_key], dates[-1]),
                key=start_key,
            )
        with col2:
            params["end_date"] = section_date_input(
                section_key,
                "End date",
                value=st.session_state[end_key],
                min_value=max(params["start_date"], dates[0]),
                max_value=dates[-1],
                key=end_key,
            )
        is_valid, error_message = validate_day_range(params["start_date"], params["end_date"])
        if not is_valid:
            st.error(error_message)
        return params, is_valid

    if comparison and primary_params:
        default_year_months = default_comparison_year_months(
            dates,
            primary_params.get("year_months")
            or [(primary_params["year"], primary_params["month"])],
        )
    else:
        default_year_months = random_year_months(dates)

    month_options = available_year_month_keys(dates)
    months_key = f"{state_key}_year_months"
    default_keys = [year_month_key(year, month) for year, month in default_year_months]
    default_keys = [key for key in default_keys if key in month_options] or month_options[:1]

    if months_key not in st.session_state:
        # Migrate older single-month widgets if present.
        legacy_year_key = f"{state_key}_year"
        legacy_month_key = f"{state_key}_month"
        if legacy_year_key in st.session_state and legacy_month_key in st.session_state:
            legacy_key = year_month_key(
                st.session_state[legacy_year_key],
                st.session_state[legacy_month_key],
            )
            st.session_state[months_key] = [legacy_key] if legacy_key in month_options else default_keys
        else:
            st.session_state[months_key] = default_keys

    selected_keys = st.multiselect(
        "Months",
        options=month_options,
        format_func=format_year_month_key,
        key=months_key,
        on_change=mark_dashboard_view_for_section,
        args=(section_key,),
    )
    selected_keys = [key for key in (selected_keys or []) if key in month_options]
    if not selected_keys:
        st.error("Select at least one month.")
        return params, False

    year_months = sorted(parse_year_month_key(value) for value in selected_keys)
    params["year_months"] = year_months
    params["year"] = year_months[0][0]
    params["month"] = year_months[0][1]
    return params, True


def render_shared_time_controls(
    section_key: str,
    dates: list[date],
    *,
    flexible_hour_window: bool = False,
    allow_compare: bool = True,
) -> tuple[dict, dict | None, bool, bool, bool]:
    """Render shared granularity and primary/comparison period controls."""
    with st.container(key=f"{section_key}_time_controls"):
        mode_col, compare_col = st.columns([3, 1], gap="small", vertical_alignment="bottom")
        with mode_col:
            mode = render_time_mode_radio(section_key)
        with compare_col:
            if allow_compare:
                compare_enabled = st.toggle(
                    "Compare periods",
                    value=False,
                    key=f"{section_key}_compare",
                    on_change=initialize_comparison_period,
                    args=(section_key, dates),
                )
            else:
                compare_enabled = False

        if compare_enabled:
            primary_col, comparison_col = st.columns(2, gap="small")
            with primary_col:
                st.markdown("**Primary period**")
                primary_params, primary_valid = render_period_controls(
                    section_key,
                    dates,
                    mode,
                    flexible_hour_window=flexible_hour_window,
                )
            with comparison_col:
                st.markdown("**Comparison period**")
                comparison_params, comparison_valid = render_period_controls(
                    section_key,
                    dates,
                    mode,
                    state_key=f"{section_key}_cmp",
                    flexible_hour_window=flexible_hour_window,
                    comparison=True,
                    primary_params=primary_params,
                )
        else:
            primary_params, primary_valid = render_period_controls(
                section_key,
                dates,
                mode,
                flexible_hour_window=flexible_hour_window,
            )
            comparison_params = None
            comparison_valid = True

    return primary_params, comparison_params, compare_enabled, primary_valid, comparison_valid


def build_time_series_df(df: pd.DataFrame, params: dict) -> tuple[pd.DataFrame, str, list | None, bool, str]:
    mode = params["mode"]

    if mode == "Hours":
        chart_df = aggregate_hourly_window(df, params["selected_date"], params["hour_labels"])
        x_col = "hour"
        x_order = [str(label) for label in sorted(params["hour_labels"], key=hour_sort_key)]
        return chart_df, x_col, x_order, False, mode

    if mode == "Day on day":
        chart_df = aggregate_daily_range(df, params["start_date"], params["end_date"])
        if chart_df.empty:
            return chart_df, "date", None, False, mode
        x_order = chart_df["date"].astype(str).tolist()
        return chart_df, "date", x_order, False, mode

    year_months = params.get("year_months") or [(params["year"], params["month"])]
    chart_df = aggregate_month_span(df, year_months)
    x_order = chart_df["date"].astype(str).tolist() if not chart_df.empty else []
    return chart_df, "date", x_order, False, mode


def volume_time_bucket_config(
    time_mode: str,
    params: dict,
    x_col: str,
    x_order: list | None,
) -> tuple[str, list[str]]:
    if time_mode == "Hours":
        bucket_col = "hour"
        bucket_order = [str(label) for label in sorted(params["hour_labels"], key=hour_sort_key)]
        return bucket_col, bucket_order

    if not x_order:
        return x_col, []

    return x_col, [str(value) for value in x_order]


def build_volume_chart_data(
    chart_df: pd.DataFrame,
    column_map: dict[str, str],
    *,
    categories_on_x_axis: bool,
    time_mode: str,
    params: dict,
    x_col: str,
    x_order: list | None,
    legend_mode: str = "default",
    fixed_legend_order: list[str] | None = None,
) -> tuple[pd.DataFrame, str, list | None, list | None]:
    if categories_on_x_axis:
        bucket_col, bucket_order = volume_time_bucket_config(time_mode, params, x_col, x_order)
        long_df, pivot_x_col, pivot_x_order, series_order = melt_time_buckets_by_category(
            chart_df,
            column_map,
            bucket_col,
            bucket_order,
        )
        return long_df, pivot_x_col, pivot_x_order, series_order

    long_df = melt_metric_columns(chart_df, x_col, column_map, x_order)
    series_order = None
    if legend_mode == "total":
        series_order = series_order_by_total(long_df)
    elif legend_mode == "fixed" and fixed_legend_order:
        series_order = series_order_from_labels(long_df, fixed_legend_order)

    if series_order:
        long_df = melt_metric_columns(chart_df, x_col, column_map, x_order, series_order)
    return long_df, x_col, x_order, series_order


def render_volume_section(df: pd.DataFrame) -> tuple[str, str] | None:
    if df.empty:
        return None

    dates = available_dates(df)
    if not dates:
        st.warning("No data available for the selected plaza.")
        return None

    params, comparison_params, compare_enabled, primary_valid, comparison_valid = render_shared_time_controls(
        "volume",
        dates,
        flexible_hour_window=True,
        allow_compare=True,
    )
    if not primary_valid or (compare_enabled and not comparison_valid):
        return None

    mode = params["mode"]

    chart_df, x_col, x_order, highlight_days, time_mode = build_time_series_df(df, params)
    axis = chart_axis_config(time_mode)
    section_kpi = ("Total vehicles", format_total_kpi(chart_df))

    render_chart_section_header("1. Vehicle class Chart")
    with st.container(key="class_chart_controls"):
        class_x_axis_dim = section_selectbox(
            "volume",
            "X-axis (vehicle class chart)",
            options=VOLUME_CLASS_X_AXIS_OPTIONS,
            key="volume_class_x_axis",
        )
    use_class_categories_on_x = class_x_axis_dim == "Vehicle class"
    class_title = volume_chart_title("class", time_mode, class_x_axis_dim)
    class_x_title = (
        volume_x_axis_title("class", time_mode, class_x_axis_dim)
        if use_class_categories_on_x
        else axis["x_axis_title"]
    )
    class_hover_label = class_x_title if use_class_categories_on_x else axis["hover_bucket_label"]
    render_comparable_line_chart(
        "volume_class",
        df,
        VEHICLE_CLASSES,
        params,
        time_mode=time_mode,
        chart_df=chart_df,
        x_col=x_col,
        x_order=x_order,
        highlight_days=highlight_days,
        categories_on_x_axis=use_class_categories_on_x,
        legend_mode="total" if not use_class_categories_on_x else "default",
        fixed_legend_order=None,
        title=class_title,
        x_axis_title=class_x_title,
        hover_bucket_label=class_hover_label,
        compare_enabled=compare_enabled,
        comparison_params=comparison_params,
    )

    render_chart_section_header("2. Lane Chart")
    with st.container(key="lane_chart_controls"):
        lane_col1, lane_col2 = st.columns(2, gap="small", vertical_alignment="bottom")
        with lane_col1:
            lane_x_axis_dim = section_selectbox(
                "volume",
                "X-axis (lane chart)",
                options=VOLUME_LANE_X_AXIS_OPTIONS,
                key="volume_lane_x_axis",
            )
        with lane_col2:
            show_all_lanes = st.toggle(
                "Show all lanes",
                value=False,
                key="show_all_lanes",
                on_change=mark_dashboard_view_for_section,
                args=("volume",),
            )

    if show_all_lanes:
        lane_map = active_lane_map(chart_df)
        lane_scope = "all active lanes"
    else:
        top = top_lanes_by_volume(chart_df)
        lane_map = {lane: col for lane, col in LANES.items() if lane in top}
        lane_scope = "top 5"

    use_lane_categories_on_x = lane_x_axis_dim == "Lanes"
    lane_title = f"{volume_chart_title('lane', time_mode, lane_x_axis_dim)} ({lane_scope})"
    lane_x_title = (
        volume_x_axis_title("lane", time_mode, lane_x_axis_dim)
        if use_lane_categories_on_x
        else axis["x_axis_title"]
    )
    lane_hover_label = lane_x_title if use_lane_categories_on_x else axis["hover_bucket_label"]
    render_comparable_line_chart(
        "volume_lane",
        df,
        lane_map,
        params,
        time_mode=time_mode,
        chart_df=chart_df,
        x_col=x_col,
        x_order=x_order,
        highlight_days=highlight_days,
        categories_on_x_axis=use_lane_categories_on_x,
        legend_mode="fixed" if not use_lane_categories_on_x else "default",
        fixed_legend_order=list(lane_map.keys()),
        title=lane_title,
        x_axis_title=lane_x_title,
        hover_bucket_label=lane_hover_label,
        compare_enabled=compare_enabled,
        comparison_params=comparison_params,
    )

    return section_kpi


def render_class_mix_section(df: pd.DataFrame) -> tuple[str, str] | None:
    dates = available_dates(df)
    if not dates:
        st.warning("No data available.")
        return None

    params, _, _, params_valid, _ = render_shared_time_controls(
        "class_mix",
        dates,
        flexible_hour_window=False,
        allow_compare=False,
    )
    if not params_valid:
        return None

    mode = params["mode"]
    filtered = filter_df_by_params(df, params)

    render_chart_section_header("Vehicle class mix")
    render_plotly_chart(
        class_bar_chart(filtered, VEHICLE_CLASSES, f"Class distribution — {mode}"),
    )
    return ("Total vehicles", format_total_kpi(filtered))


def render_mop_section(df: pd.DataFrame) -> tuple[str, str] | None:
    dates = available_dates(df)
    if not dates:
        st.warning("No data available.")
        return None

    params, comparison_params, compare_enabled, primary_valid, comparison_valid = render_shared_time_controls(
        "mop",
        dates,
        flexible_hour_window=False,
        allow_compare=True,
    )
    if not primary_valid or (compare_enabled and not comparison_valid):
        return None

    mode = params["mode"]
    chart_df, x_col, x_order, highlight_days, time_mode = build_time_series_df(df, params)
    axis = chart_axis_config(time_mode)
    section_kpi = ("Total transactions", format_total_kpi(chart_df))

    render_chart_section_header("FASTag / Cash / Exempt over time")
    with st.container(key="mop_chart_controls"):
        show_pct_share = st.toggle(
            "Show as % share",
            value=False,
            key="mop_show_pct_share",
            on_change=mark_dashboard_view_for_section,
            args=("mop",),
            help="Each hour/day shows MOP category share of that bucket's total transactions.",
        )

    render_comparable_line_chart(
        "mop",
        df,
        MOP_TYPES,
        params,
        time_mode=time_mode,
        chart_df=chart_df,
        x_col=x_col,
        x_order=x_order,
        highlight_days=highlight_days,
        categories_on_x_axis=False,
        legend_mode="total",
        fixed_legend_order=None,
        title=mop_chart_title(time_mode, as_percent=show_pct_share),
        x_axis_title=axis["x_axis_title"],
        hover_bucket_label=axis["hover_bucket_label"],
        compare_enabled=compare_enabled,
        comparison_params=comparison_params,
        y_title="Share (%)" if show_pct_share else "Transaction count",
        total_label="Total transactions",
        as_percent=show_pct_share,
        value_suffix="%" if show_pct_share else "",
    )

    if not compare_enabled:
        render_mop_share_table(chart_df)
    elif comparison_params is not None:
        compare_chart_df, _, _, _, _ = build_time_series_df(df, comparison_params)
        left_col, right_col = st.columns(2, gap="small")
        with left_col:
            render_mop_share_table(chart_df, caption="Primary — category share")
        with right_col:
            render_mop_share_table(compare_chart_df, caption="Comparison — category share")

    return section_kpi


def exempt_chart_title(time_mode: str, x_axis_dim: str) -> str:
    if x_axis_dim == "Lanes":
        return "Exempt count by lanes"
    x_label_by_mode = {
        "Hours": "hours",
        "Day on day": "day on day",
        "Month": "month",
    }
    return f"Exempt count by {x_label_by_mode.get(time_mode, 'time')}"


def render_exempt_section(exempt_df: pd.DataFrame) -> tuple[str, str] | None:
    dates = available_dates(exempt_df)
    if not dates:
        st.warning("No exempt distribution data for the selected plaza. Run module3.py first.")
        return ("Exempt vehicles", "—")

    params, comparison_params, compare_enabled, primary_valid, comparison_valid = render_shared_time_controls(
        "exempt",
        dates,
        flexible_hour_window=True,
        allow_compare=True,
    )
    if not primary_valid or (compare_enabled and not comparison_valid):
        return None

    chart_df, x_col, x_order, highlight_days, time_mode = build_time_series_df(exempt_df, params)
    axis = chart_axis_config(time_mode)
    section_kpi = ("Exempt vehicles", format_total_kpi(chart_df))

    render_chart_section_header("Exempt vehicles by lane")
    with st.container(key="exempt_lane_controls"):
        lane_col1, lane_col2 = st.columns(2, gap="small", vertical_alignment="bottom")
        with lane_col1:
            lane_x_axis_dim = section_selectbox(
                "exempt",
                "X-axis",
                options=VOLUME_LANE_X_AXIS_OPTIONS,
                key="exempt_lane_x_axis",
            )
        with lane_col2:
            show_all_lanes = st.toggle(
                "Show all lanes",
                value=False,
                key="exempt_show_all_lanes",
                on_change=mark_dashboard_view_for_section,
                args=("exempt",),
            )

    if show_all_lanes:
        lane_map = active_lane_map(chart_df)
        lane_scope = "all active lanes"
    else:
        top = top_lanes_by_volume(chart_df)
        lane_map = {lane: col for lane, col in LANES.items() if lane in top}
        lane_scope = "top 5"

    if not lane_map:
        st.info("No exempt vehicles for the selected period.")
        return section_kpi

    use_lane_categories_on_x = lane_x_axis_dim == "Lanes"
    lane_title = f"{exempt_chart_title(time_mode, lane_x_axis_dim)} ({lane_scope})"
    lane_x_title = (
        "Lane"
        if use_lane_categories_on_x
        else axis["x_axis_title"]
    )
    lane_hover_label = lane_x_title if use_lane_categories_on_x else axis["hover_bucket_label"]

    render_comparable_line_chart(
        "exempt_lanes",
        exempt_df,
        lane_map,
        params,
        time_mode=time_mode,
        chart_df=chart_df,
        x_col=x_col,
        x_order=x_order,
        highlight_days=highlight_days,
        categories_on_x_axis=use_lane_categories_on_x,
        legend_mode="fixed" if not use_lane_categories_on_x else "default",
        fixed_legend_order=list(lane_map.keys()),
        title=lane_title,
        x_axis_title=lane_x_title,
        hover_bucket_label=lane_hover_label,
        compare_enabled=compare_enabled,
        comparison_params=comparison_params,
        y_title="Exempt vehicles",
        total_label="Exempt vehicles",
    )

    return section_kpi


def gap_chart_title(time_mode: str) -> str:
    x_label_by_mode = {
        "Hours": "hours",
        "Day on day": "day on day",
        "Month": "month",
    }
    return f"Average headway by {x_label_by_mode.get(time_mode, 'time')}"


def build_gap_line_figure(
    chart_df: pd.DataFrame,
    *,
    x_col: str,
    x_order: list | None,
    selected_lanes: list[str],
    title: str,
    x_axis_title: str,
    period_label: str,
    time_mode: str,
    highlight_days: bool,
    compact: bool = False,
    show_lt2_overlay: bool = False,
):
    long_df = gap_avg_long_df(chart_df, x_col, x_order, selected_lanes)
    present = set(long_df["series"].astype(str)) if not long_df.empty else set()
    series_order = [lane for lane in LANES if lane in selected_lanes and (not present or lane in present)]

    series_totals = {
        lane: total
        for lane, total in gap_lane_vehicle_totals(chart_df).items()
        if lane in selected_lanes
    }
    x_tick_stride = day_x_tick_stride(time_mode, x_order, compact=compact)
    lt2_overlay_df = None
    if show_lt2_overlay:
        overlay = gap_lt2_overlay_long_df(chart_df, x_col, selected_lanes)
        lt2_overlay_df = overlay if not overlay.empty else None

    return line_series_chart(
        long_df,
        x_col,
        f"{title} — {period_label}",
        y_title="Avg gap (seconds)",
        x_axis_title=x_axis_title,
        hover_bucket_label=x_axis_title,
        x_order=x_order,
        series_order=series_order or None,
        highlight_every_nth_day=5 if highlight_days else None,
        compact=compact,
        series_totals=series_totals or None,
        x_tick_stride=x_tick_stride,
        value_suffix="s",
        lt2_overlay_df=lt2_overlay_df,
    )


def render_gap_summary_tables(
    chart_df: pd.DataFrame,
    *,
    x_col: str,
    selected_lanes: list[str],
    axis: dict[str, str],
    period_label: str,
    avg_caption: str | None = None,
    flag_caption: str | None = None,
    side_by_side: bool = True,
) -> None:
    """Per-lane average and abnormal <2s flag tables (one row by default)."""
    avg_table = gap_lane_avg_table(chart_df, selected_lanes)
    flag_table = gap_lt2_flag_table(chart_df, x_col, selected_lanes)
    avg_caption_text = avg_caption or "Per-lane average"
    flag_caption_text = flag_caption or (
        f"Abnormal gaps (< 2s) — flagged lane × {axis['x_axis_title'].lower()} — {period_label}"
    )

    def _render_avg(container) -> None:
        with container:
            st.caption(avg_caption_text)
            if avg_table.empty:
                st.info("No per-lane averages for the selected filters.")
            else:
                st.dataframe(avg_table, hide_index=True, width="stretch")

    def _render_flags(container) -> None:
        with container:
            st.caption(flag_caption_text)
            if flag_table.empty:
                st.info("No gaps under 2s in the selected lanes/period.")
            else:
                st.dataframe(
                    flag_table,
                    hide_index=True,
                    width="stretch",
                    height=min(360, 42 + 35 * len(flag_table)),
                )

    if side_by_side:
        left_col, right_col = st.columns(2, gap="medium")
        _render_avg(left_col)
        _render_flags(right_col)
        return

    _render_avg(st.container())
    _render_flags(st.container())


def render_gap_period_charts(
    chart_df: pd.DataFrame,
    *,
    selected_lanes: list[str],
    params: dict,
    time_mode: str,
    x_col: str,
    x_order: list | None,
    highlight_days: bool,
    axis: dict[str, str],
    compact: bool = False,
    show_tables: bool = True,
    show_lt2_overlay: bool = False,
) -> None:
    period_label = format_period_label(params)
    render_plotly_chart(
        build_gap_line_figure(
            chart_df,
            x_col=x_col,
            x_order=x_order,
            selected_lanes=selected_lanes,
            title=gap_chart_title(time_mode),
            x_axis_title=axis["x_axis_title"],
            period_label=period_label,
            time_mode=time_mode,
            highlight_days=highlight_days,
            compact=compact,
            show_lt2_overlay=show_lt2_overlay,
        )
    )

    if show_tables:
        render_gap_summary_tables(
            chart_df,
            x_col=x_col,
            selected_lanes=selected_lanes,
            axis=axis,
            period_label=period_label,
        )


def render_gap_section(gap_df: pd.DataFrame) -> tuple[str, str] | None:
    dates = available_dates(gap_df)
    if not dates:
        st.warning("No gap distribution data for the selected plaza. Run module2.py first.")
        return ("Avg gap", "—")

    params, comparison_params, compare_enabled, primary_valid, comparison_valid = render_shared_time_controls(
        "gap",
        dates,
        flexible_hour_window=True,
        allow_compare=True,
    )
    if not primary_valid or (compare_enabled and not comparison_valid):
        return None

    chart_df, x_col, x_order, highlight_days, time_mode = build_gap_time_series(gap_df, params)
    axis = chart_axis_config(time_mode)

    render_chart_section_header("Lane gap (headway)")
    with st.container(key="gap_lane_controls"):
        toggle_cols = st.columns(2, gap="large", vertical_alignment="center")
        with toggle_cols[0]:
            show_all_lanes = st.toggle(
                "Show all lanes",
                value=False,
                key="gap_show_all_lanes",
                on_change=mark_dashboard_view_for_section,
                args=("gap",),
            )
        with toggle_cols[1]:
            show_lt2_overlay = st.toggle(
                "Mark <2s gaps on chart",
                value=False,
                key="gap_show_lt2_overlay",
                on_change=mark_dashboard_view_for_section,
                args=("gap",),
                help="Diamond markers on the avg-gap line where that lane had at least one gap under 2 seconds.",
            )

    if show_all_lanes:
        lane_options = active_gap_lanes(chart_df)
    else:
        lane_options = top_gap_lanes_by_volume(chart_df)

    if not lane_options:
        st.info("No lane gap samples for the selected period.")
        return ("Avg gap", "—")

    selected_lanes = render_category_selector("gap_lanes", lane_options)
    if not selected_lanes:
        selected_lanes = lane_options

    section_kpi = ("Avg gap", weighted_avg_gap_kpi(chart_df, selected_lanes))

    if not compare_enabled:
        render_gap_period_charts(
            chart_df,
            selected_lanes=selected_lanes,
            params=params,
            time_mode=time_mode,
            x_col=x_col,
            x_order=x_order,
            highlight_days=highlight_days,
            axis=axis,
            compact=False,
            show_tables=True,
            show_lt2_overlay=show_lt2_overlay,
        )
        return section_kpi

    if comparison_params is None:
        return section_kpi

    left_col, right_col = st.columns(2, gap="small")
    with left_col:
        st.metric("Avg gap", weighted_avg_gap_kpi(chart_df, selected_lanes))
        render_gap_period_charts(
            chart_df,
            selected_lanes=selected_lanes,
            params=params,
            time_mode=time_mode,
            x_col=x_col,
            x_order=x_order,
            highlight_days=highlight_days,
            axis=axis,
            compact=True,
            show_tables=False,
            show_lt2_overlay=show_lt2_overlay,
        )
        render_gap_summary_tables(
            chart_df,
            x_col=x_col,
            selected_lanes=selected_lanes,
            axis=axis,
            period_label=format_period_label(params),
            avg_caption="Primary — per-lane average",
            flag_caption="Primary — abnormal gaps (< 2s)",
            side_by_side=False,
        )

    with right_col:
        compare_chart_df, compare_x_col, compare_x_order, compare_highlight_days, _ = build_gap_time_series(
            gap_df,
            comparison_params,
        )
        st.metric("Avg gap", weighted_avg_gap_kpi(compare_chart_df, selected_lanes))
        render_gap_period_charts(
            compare_chart_df,
            selected_lanes=selected_lanes,
            params=comparison_params,
            time_mode=time_mode,
            x_col=compare_x_col,
            x_order=compare_x_order,
            highlight_days=compare_highlight_days,
            axis=axis,
            compact=True,
            show_tables=False,
            show_lt2_overlay=show_lt2_overlay,
        )
        render_gap_summary_tables(
            compare_chart_df,
            x_col=compare_x_col,
            selected_lanes=selected_lanes,
            axis=axis,
            period_label=format_period_label(comparison_params),
            avg_caption="Comparison — per-lane average",
            flag_caption="Comparison — abnormal gaps (< 2s)",
            side_by_side=False,
        )

    return section_kpi


def main() -> None:
    apply_compact_control_styles()

    try:
        plazas = fetch_plaza_names()
    except Exception as exc:
        st.error(f"Database connection failed: {exc}")
        st.stop()

    if not plazas:
        st.warning("No plaza data found in the analytics table. Run module1.py first.")
        st.stop()

    with st.sidebar:
        selected_plaza = st.selectbox("Plaza", plazas)
        if st.button("Refresh data"):
            load_data.clear()
            load_gap_data.clear()
            load_exempt_data.clear()

    df = load_data(selected_plaza)
    st.session_state["df"] = df

    try:
        gap_df = load_gap_data(selected_plaza)
    except Exception:
        gap_df = pd.DataFrame()
    st.session_state["gap_df"] = gap_df

    try:
        exempt_df = load_exempt_data(selected_plaza)
    except Exception:
        exempt_df = pd.DataFrame()
    st.session_state["exempt_df"] = exempt_df

    kpi_slot = render_dashboard_title()

    if df.empty:
        st.warning(f"No analytics rows for plaza '{selected_plaza}'.")
        render_dashboard_kpi(kpi_slot, "Total transactions", "0")
        st.stop()

    st.session_state.setdefault("dashboard_kpi_source", VIEW_VOLUME)

    tab_volume, tab_class_mix, tab_mop, tab_gap, tab_exempt = st.tabs(list(DASHBOARD_VIEWS))

    with tab_volume:
        render_volume_section(df)
    with tab_class_mix:
        render_class_mix_section(df)
    with tab_mop:
        render_mop_section(df)
    with tab_gap:
        render_gap_section(gap_df)
    with tab_exempt:
        render_exempt_section(exempt_df)

    active_view = resolve_active_dashboard_view()
    section_kpi = compute_section_kpi(df, active_view)
    active_section_key = {
        VIEW_VOLUME: "volume",
        VIEW_CLASS_MIX: "class_mix",
        VIEW_MOP: "mop",
        VIEW_GAP: "gap",
        VIEW_EXEMPT: "exempt",
    }.get(active_view)
    comparison_active = bool(active_section_key and st.session_state.get(f"{active_section_key}_compare"))
    if section_kpi and not comparison_active:
        kpi_label, kpi_value = section_kpi
        render_dashboard_kpi(kpi_slot, kpi_label, kpi_value)


if __name__ == "__main__":
    main()
