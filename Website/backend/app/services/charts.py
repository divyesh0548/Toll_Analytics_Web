"""Plotly chart builders."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.utils.analytics_config import CHART_HEIGHT

PLOTLY_TEMPLATE = None
CHART_HEIGHT_COMPARE = 520


def _base_layout(
    title: str,
    y_title: str,
    *,
    show_legend: bool = True,
    hovermode: str = "x unified",
    height: int | None = None,
) -> dict:
    layout = dict(
        height=height or CHART_HEIGHT,
        autosize=True,
        title=dict(
            text=title,
            x=0,
            xanchor="left",
            y=0.98,
            yanchor="top",
            font=dict(size=17),
        ),
        margin=dict(l=58, r=28, t=68, b=150 if show_legend else 84),
        yaxis_title=y_title,
        hovermode=hovermode,
        xaxis=dict(
            automargin=True,
            fixedrange=True,
            showgrid=False,
            ticks="outside",
            tickfont=dict(size=12),
            title_font=dict(size=13),
            title_standoff=14,
        ),
        yaxis=dict(
            automargin=True,
            fixedrange=True,
            tickfont=dict(size=12),
            title_font=dict(size=13),
            title_standoff=12,
        ),
    )
    if PLOTLY_TEMPLATE:
        layout["template"] = PLOTLY_TEMPLATE
    if show_legend:
        layout["legend"] = dict(
            orientation="h",
            yanchor="top",
            y=-0.28,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            font=dict(size=14),
            tracegroupgap=10,
            itemclick="toggleothers",
            itemdoubleclick="toggle",
        )
    return layout


def _configure_category_xaxis(
    fig: go.Figure,
    x_order: list[str] | None,
    x_axis_title: str,
    x_value_totals: dict[str, int] | None = None,
    tick_stride: int = 1,
) -> None:
    categories = [str(value) for value in x_order] if x_order else None
    tickvals = categories
    if categories and tick_stride > 1:
        tickvals = categories[::tick_stride]
        if categories[-1] not in tickvals:
            tickvals = [*tickvals, categories[-1]]

    ticktext = tickvals
    if tickvals and x_value_totals:
        ticktext = [
            f"{category}<br>({x_value_totals[category]:,})"
            if category in x_value_totals
            else category
            for category in tickvals
        ]
    fig.update_xaxes(
        title=x_axis_title,
        type="category",
        categoryorder="array" if categories else "category ascending",
        categoryarray=categories,
        tickmode="array" if categories else "auto",
        tickvals=tickvals,
        ticktext=ticktext,
    )


def _apply_monthly_highlights(fig: go.Figure, categories: list[str], every_n: int = 5) -> None:
    ticktext: list[str] = []
    for index, label in enumerate(categories, start=1):
        day_num = int(label) if str(label).isdigit() else index
        ticktext.append(f"<b>{label}</b>" if day_num % every_n == 0 else str(label))

    fig.update_xaxes(tickmode="array", tickvals=categories, ticktext=ticktext)


def _series_color_map(fig: go.Figure) -> dict[str, str]:
    colors: dict[str, str] = {}
    for trace in fig.data:
        if not trace.name:
            continue
        color = None
        if trace.line and trace.line.color:
            color = trace.line.color
        elif trace.marker and trace.marker.color:
            color = trace.marker.color
        if color:
            colors[str(trace.name)] = color
    return colors


def _apply_legend_order(fig: go.Figure, series_order: list[str] | None) -> None:
    if not series_order:
        return
    order_map = {str(name): index for index, name in enumerate(series_order)}
    named_traces = [trace for trace in fig.data if trace.name and str(trace.name) in order_map]
    other_traces = [trace for trace in fig.data if not trace.name or str(trace.name) not in order_map]
    named_traces.sort(key=lambda trace: order_map[str(trace.name)])
    fig.data = tuple(named_traces + other_traces)


def _disable_series_hovers(fig: go.Figure) -> None:
    for trace in fig.data:
        if not trace.name:
            continue
        # Keep independent hover on <2s overlay diamonds.
        if str(trace.name).endswith(" <2s"):
            continue
        trace.hoverinfo = "skip"
        trace.hovertemplate = None


def _format_hover_value(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number - round(number)) < 1e-9:
        return f"{int(round(number)):,}"
    return f"{number:,.2f}"


def _apply_sorted_x_hover(
    fig: go.Figure,
    plot_df: pd.DataFrame,
    x_col: str,
    categories: list[str],
    *,
    value_suffix: str = "",
) -> None:
    """Single x-aligned hover box with color swatches, sorted by count (descending)."""
    series_colors = _series_color_map(fig)
    hover_texts: list[str] = []

    for x_val in categories:
        subset = plot_df[plot_df[x_col] == str(x_val)].sort_values("count", ascending=False)
        if subset.empty:
            hover_texts.append("No data")
            continue
        lines = [
            (
                f"<span style='color:{series_colors.get(str(row['series']), 'currentColor')}'>█</span> "
                f"{row['series']}: {_format_hover_value(row['count'])}{value_suffix}"
            )
            for _, row in subset.iterrows()
        ]
        hover_texts.append("<br><br>".join(lines))

    _disable_series_hovers(fig)

    y_anchor = float(plot_df["count"].max()) * 0.5 if not plot_df.empty else 0
    fig.add_trace(
        go.Scatter(
            x=categories,
            y=[y_anchor] * len(categories),
            mode="markers",
            marker=dict(size=24, opacity=0),
            hoverinfo="text",
            hovertemplate="<b>%{x}</b><br>%{customdata}<extra></extra>",
            customdata=hover_texts,
            showlegend=False,
            name="",
        )
    )


def _format_series_labels(
    plot_df: pd.DataFrame,
    series_order: list[str] | None,
    series_totals: dict[str, int] | None,
) -> tuple[pd.DataFrame, list[str] | None]:
    if not series_totals:
        return plot_df, series_order

    label_map = {
        str(series): f"{series} ({total:,})"
        for series, total in series_totals.items()
    }
    out = plot_df.copy()
    out["series"] = out["series"].map(lambda value: label_map.get(str(value), str(value)))
    if series_order:
        series_order = [label_map.get(str(value), str(value)) for value in series_order]
    return out, series_order


def line_series_chart(
    long_df: pd.DataFrame,
    x_col: str,
    title: str,
    y_title: str = "Vehicle count",
    x_axis_title: str = "Time",
    hover_bucket_label: str = "Time",
    x_order: list[str] | None = None,
    series_order: list[str] | None = None,
    highlight_every_nth_day: int | None = None,
    compact: bool = False,
    series_totals: dict[str, int] | None = None,
    x_value_totals: dict[str, int] | None = None,
    x_tick_stride: int = 1,
    value_suffix: str = "",
    lt2_overlay_df: pd.DataFrame | None = None,
) -> go.Figure:
    chart_height = CHART_HEIGHT_COMPARE if compact else None
    if long_df.empty:
        fig = go.Figure()
        fig.update_layout(**_base_layout(title, y_title, height=chart_height))
        fig.add_annotation(text="No data for the selected filters", showarrow=False, y=0.5, x=0.5)
        return fig

    plot_df = long_df.copy()
    plot_df[x_col] = plot_df[x_col].astype(str)
    plot_df["series"] = plot_df["series"].astype(str)
    plot_df, series_order = _format_series_labels(plot_df, series_order, series_totals)

    category_orders: dict[str, list[str]] = {}
    if x_order:
        category_orders[x_col] = [str(value) for value in x_order]
    if series_order:
        category_orders["series"] = [str(value) for value in series_order]

    fig = px.line(
        plot_df,
        x=x_col,
        y="count",
        color="series",
        markers=True,
        category_orders=category_orders or None,
        labels={x_col: x_axis_title, "count": y_title, "series": ""},
    )
    _apply_legend_order(fig, [str(value) for value in series_order] if series_order else None)
    fig.update_layout(**_base_layout(title, y_title, hovermode="x", height=chart_height))
    fig.update_layout(hoverdistance=-1, spikedistance=-1)
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor", fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    fig.update_traces(line=dict(width=2.4), marker=dict(size=6))

    categories = [str(value) for value in x_order] if x_order else list(dict.fromkeys(plot_df[x_col]))
    _configure_category_xaxis(
        fig,
        categories,
        x_axis_title,
        x_value_totals=x_value_totals,
        tick_stride=x_tick_stride,
    )
    fig.update_xaxes(hoverformat=None)

    if highlight_every_nth_day and categories:
        _apply_monthly_highlights(fig, categories, every_n=highlight_every_nth_day)

    if lt2_overlay_df is not None and not lt2_overlay_df.empty:
        _add_lt2_overlay_markers(fig, lt2_overlay_df, x_col, series_totals=series_totals)

    _apply_sorted_x_hover(fig, plot_df, x_col, categories, value_suffix=value_suffix)
    return fig


def _add_lt2_overlay_markers(
    fig: go.Figure,
    overlay_df: pd.DataFrame,
    x_col: str,
    *,
    series_totals: dict[str, int] | None = None,
) -> None:
    """Sparse markers where <2s gaps occurred (y = avg gap at that point)."""
    series_colors = _series_color_map(fig)
    label_map = {}
    if series_totals:
        label_map = {
            str(series): f"{series} ({total:,})"
            for series, total in series_totals.items()
        }

    plot = overlay_df.copy()
    plot[x_col] = plot[x_col].astype(str)
    plot["series"] = plot["series"].astype(str)
    plot["gap_lt_2s_count"] = pd.to_numeric(plot["gap_lt_2s_count"], errors="coerce").fillna(0)

    for series_name, group in plot.groupby("series", sort=False):
        legend_name = label_map.get(str(series_name), str(series_name))
        color = series_colors.get(legend_name) or series_colors.get(str(series_name)) or "#c0392b"
        sizes = [min(10 + int(count) * 2, 28) for count in group["gap_lt_2s_count"]]
        fig.add_trace(
            go.Scatter(
                x=group[x_col].astype(str).tolist(),
                y=group["count"].tolist(),
                mode="markers",
                name=f"{series_name} <2s",
                marker=dict(
                    size=sizes,
                    color=color,
                    symbol="diamond",
                    line=dict(width=1.2, color="#111111"),
                    opacity=0.9,
                ),
                customdata=group["gap_lt_2s_count"].tolist(),
                hovertemplate=(
                    f"<b>{series_name}</b><br>"
                    "%{x}<br>"
                    "Avg gap: %{y:.2f}s<br>"
                    "&lt;2s gaps: %{customdata}<extra></extra>"
                ),
                showlegend=True,
            )
        )


def gap_lt2_heatmap_chart(
    matrix_df: pd.DataFrame,
    title: str,
    *,
    x_axis_title: str = "Time",
    compact: bool = False,
) -> go.Figure:
    chart_height = CHART_HEIGHT_COMPARE if compact else None
    if matrix_df.empty:
        fig = go.Figure()
        fig.update_layout(**_base_layout(title, "Lane", show_legend=False, height=chart_height))
        fig.add_annotation(text="No <2s gap flags for the selected filters", showarrow=False, y=0.5, x=0.5)
        return fig

    z_values = matrix_df.to_numpy(dtype=float)
    fig = go.Figure(
        data=go.Heatmap(
            z=z_values,
            x=[str(col) for col in matrix_df.columns],
            y=[str(idx) for idx in matrix_df.index],
            colorscale="YlOrRd",
            colorbar=dict(title="<2s gaps"),
            hovertemplate="Lane: %{y}<br>%{x}<br>&lt;2s gaps: %{z}<extra></extra>",
            zmin=0,
        )
    )
    fig.update_layout(**_base_layout(title, "Lane", show_legend=False, hovermode="closest", height=chart_height))
    fig.update_xaxes(title=x_axis_title, type="category", fixedrange=True)
    fig.update_yaxes(title="Lane", type="category", fixedrange=True, autorange="reversed")
    return fig


def gap_distribution_box_chart(
    dist_df: pd.DataFrame,
    title: str,
    *,
    compact: bool = False,
) -> go.Figure:
    """
    One box per lane using stored distribution stats.
    Whiskers = min/max, box edges = p10/p90, center = median.
    """
    chart_height = CHART_HEIGHT_COMPARE if compact else None
    if dist_df.empty:
        fig = go.Figure()
        fig.update_layout(**_base_layout(title, "Gap (seconds)", show_legend=False, height=chart_height))
        fig.add_annotation(text="No data for the selected filters", showarrow=False, y=0.5, x=0.5)
        return fig

    fig = go.Figure()
    for _, row in dist_df.iterrows():
        lane = str(row["lane_no"])
        if pd.isna(row.get("median_gap_sec")):
            continue
        lower = row.get("min_gap_sec")
        q1 = row.get("p10_gap_sec")
        median = row.get("median_gap_sec")
        q3 = row.get("p90_gap_sec")
        upper = row.get("max_gap_sec")
        avg = row.get("avg_gap_sec")

        # Plotly box with precomputed quartiles (p10/p90 used as box edges).
        fig.add_trace(
            go.Box(
                name=lane,
                q1=[q1],
                median=[median],
                q3=[q3],
                lowerfence=[lower],
                upperfence=[upper],
                mean=[avg] if pd.notna(avg) else None,
                boxmean=True if pd.notna(avg) else False,
                boxpoints=False,
                hovertemplate=(
                    f"<b>{lane}</b><br>"
                    f"Min: {_format_hover_value(lower)}s<br>"
                    f"P10: {_format_hover_value(q1)}s<br>"
                    f"Median: {_format_hover_value(median)}s<br>"
                    f"Avg: {_format_hover_value(avg)}s<br>"
                    f"P90: {_format_hover_value(q3)}s<br>"
                    f"Max: {_format_hover_value(upper)}s"
                    "<extra></extra>"
                ),
            )
        )

    if not fig.data:
        fig.update_layout(**_base_layout(title, "Gap (seconds)", show_legend=False, height=chart_height))
        fig.add_annotation(text="No gap samples for the selected filters", showarrow=False, y=0.5, x=0.5)
        return fig

    fig.update_layout(
        **_base_layout(title, "Gap (seconds)", show_legend=False, hovermode="closest", height=chart_height),
        boxmode="group",
    )
    fig.update_xaxes(title="Lane", type="category", fixedrange=True)
    fig.update_yaxes(fixedrange=True, rangemode="tozero")
    return fig


def class_bar_chart(df: pd.DataFrame, column_map: dict[str, str], title: str) -> go.Figure:
    if df.empty:
        fig = go.Figure()
        fig.update_layout(**_base_layout(title, "Count", show_legend=False, hovermode="closest"))
        fig.add_annotation(text="No data for the selected filters", showarrow=False, y=0.5, x=0.5)
        return fig

    totals = {label: int(df[col].sum()) for label, col in column_map.items() if col in df.columns}
    chart_df = pd.DataFrame(
        {"class": list(totals.keys()), "count": list(totals.values())}
    )
    grand_total = chart_df["count"].sum()
    chart_df["pct"] = chart_df["count"].apply(
        lambda value: (value / grand_total * 100) if grand_total else 0
    )
    chart_df["pct_label"] = chart_df["pct"].map(lambda value: f"{value:.1f}%")

    fig = px.bar(
        chart_df,
        x="class",
        y="count",
        text="pct_label",
        labels={"class": "Vehicle class", "count": "Count"},
    )
    fig.update_layout(
        **_base_layout(title, "Count", show_legend=False, hovermode="closest"),
        showlegend=False,
    )
    fig.update_xaxes(title="Vehicle class", type="category", tickangle=-30)
    fig.update_traces(
        textposition="outside",
        marker_line_width=0,
        hovertemplate=(
            "<b>%{x}</b><br>"
            "Count: %{y:,}<br>"
            "Share: %{text}<extra></extra>"
        ),
    )
    return fig
