"""Database access for the analytics dashboard."""

from __future__ import annotations

import os

import pandas as pd
import psycopg2

from app.utils.analytics_config import (
    GAP_DISTRIBUTION_TABLE,
    LANES,
    MOP_DISTRIBUTION_PER_CLASS_TABLE,
    MOP_DISTRIBUTION_PER_LANE_TABLE,
)
from app.utils.db import get_db_connection_kwargs

DEFAULT_GAP_DISTRIBUTION_TABLE = GAP_DISTRIBUTION_TABLE
LANE_DB_COLUMNS = dict(LANES)


def get_analytics_db_connection_kwargs() -> dict:
    """Prefer ANALYTICS_DB_NAME when analytics lives in a separate database."""
    analytics_db = os.environ.get("ANALYTICS_DB_NAME", "").strip()
    return get_db_connection_kwargs(database=analytics_db or None)


def get_analytics_table_name() -> str:
    return (
        os.environ.get("ANALYTICS_TABLE", "").strip()
        or MOP_DISTRIBUTION_PER_CLASS_TABLE
    )


def _apply_common_filters(query: str, params: list, *, plaza_name=None, plaza_identifier=None, start_date=None, end_date=None):
    if plaza_identifier:
        query += " AND plaza_identifier = %s"
        params.append(plaza_identifier)
    elif plaza_name:
        query += " AND plaza_name = %s"
        params.append(plaza_name)
    if start_date is not None:
        query += " AND date >= %s"
        params.append(start_date)
    if end_date is not None:
        query += " AND date <= %s"
        params.append(end_date)
    return query, params


def fetch_analytics(
    plaza_name: str | None = None,
    plaza_identifier: str | None = None,
    start_date=None,
    end_date=None,
) -> pd.DataFrame:
    """Fetch class × MOP hourly rows (primary volume insight table)."""
    table_name = get_analytics_table_name()
    query = f"SELECT * FROM {table_name} WHERE 1=1"
    params: list = []
    query, params = _apply_common_filters(
        query,
        params,
        plaza_name=plaza_name,
        plaza_identifier=plaza_identifier,
        start_date=start_date,
        end_date=end_date,
    )
    query += " ORDER BY date, hour"

    with psycopg2.connect(**get_analytics_db_connection_kwargs()) as conn:
        df = pd.read_sql(query, conn, params=params or None)

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def fetch_plaza_names() -> list[str]:
    table_name = get_analytics_table_name()
    query = f"SELECT DISTINCT plaza_name FROM {table_name} ORDER BY plaza_name"

    with psycopg2.connect(**get_analytics_db_connection_kwargs()) as conn:
        df = pd.read_sql(query, conn)

    return df["plaza_name"].tolist()


def get_gap_distribution_table_name() -> str:
    return (
        os.environ.get("GAP_DISTRIBUTION_TABLE", "").strip()
        or DEFAULT_GAP_DISTRIBUTION_TABLE
    )


def melt_gap_wide_to_long(df: pd.DataFrame) -> pd.DataFrame:
    """Convert wide l01…l12 avg-gap (+ optional lt2) columns into long rows for gap charts."""
    if df.empty:
        return df

    value_cols = [col for col in LANE_DB_COLUMNS.values() if col in df.columns]
    if not value_cols:
        return df

    id_vars = [
        col
        for col in ("plaza_identifier", "plaza_name", "date", "hour")
        if col in df.columns
    ]
    long_df = df.melt(
        id_vars=id_vars,
        value_vars=value_cols,
        var_name="_lane_col",
        value_name="avg_gap_sec",
    )
    col_to_lane = {col: lane for lane, col in LANE_DB_COLUMNS.items()}
    long_df["lane_no"] = long_df["_lane_col"].map(col_to_lane)
    long_df = long_df.drop(columns=["_lane_col"])

    lt2_col_to_lane = {f"{col}_lt2_count": lane for lane, col in LANE_DB_COLUMNS.items()}
    lt2_cols = [col for col in lt2_col_to_lane if col in df.columns]
    if lt2_cols:
        lt2_long = df.melt(
            id_vars=id_vars,
            value_vars=lt2_cols,
            var_name="_lt2_col",
            value_name="gap_lt_2s_count",
        )
        lt2_long["lane_no"] = lt2_long["_lt2_col"].map(lt2_col_to_lane)
        lt2_long = lt2_long.drop(columns=["_lt2_col"])
        long_df = long_df.merge(lt2_long, on=[*id_vars, "lane_no"], how="left")
    else:
        long_df["gap_lt_2s_count"] = 0

    long_df = long_df[long_df["avg_gap_sec"].notna()].copy()
    long_df["gap_lt_2s_count"] = (
        pd.to_numeric(long_df["gap_lt_2s_count"], errors="coerce").fillna(0).astype(int)
    )
    long_df["gap_count"] = 1
    long_df["vehicle_count"] = 1
    long_df["median_gap_sec"] = long_df["avg_gap_sec"]
    long_df["p10_gap_sec"] = long_df["avg_gap_sec"]
    long_df["p90_gap_sec"] = long_df["avg_gap_sec"]
    long_df["min_gap_sec"] = long_df["avg_gap_sec"]
    long_df["max_gap_sec"] = long_df["avg_gap_sec"]
    return long_df


def fetch_gap_distribution(
    plaza_name: str | None = None,
    plaza_identifier: str | None = None,
    start_date=None,
    end_date=None,
) -> pd.DataFrame:
    table_name = get_gap_distribution_table_name()
    query = f"SELECT * FROM {table_name} WHERE 1=1"
    params: list = []
    query, params = _apply_common_filters(
        query,
        params,
        plaza_name=plaza_name,
        plaza_identifier=plaza_identifier,
        start_date=start_date,
        end_date=end_date,
    )
    query += " ORDER BY date, hour"

    with psycopg2.connect(**get_analytics_db_connection_kwargs()) as conn:
        df = pd.read_sql(query, conn, params=params or None)

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["hour"] = df["hour"].astype(str)
    long_df = melt_gap_wide_to_long(df)
    if long_df.empty:
        return long_df
    long_df["lane_no"] = long_df["lane_no"].astype(str)
    return long_df


def get_mop_lane_table_name() -> str:
    return (
        os.environ.get("MOP_DISTRIBUTION_PER_LANE_TABLE", "").strip()
        or MOP_DISTRIBUTION_PER_LANE_TABLE
    )


def fetch_exempt_distribution(
    plaza_name: str | None = None,
    plaza_identifier: str | None = None,
    start_date=None,
    end_date=None,
) -> pd.DataFrame:
    """Exempt counts by lane from mop_distribution_per_lane (mop = exempt)."""
    table_name = get_mop_lane_table_name()
    query = f"SELECT * FROM {table_name} WHERE mop = %s"
    params: list = ["exempt"]
    query, params = _apply_common_filters(
        query,
        params,
        plaza_name=plaza_name,
        plaza_identifier=plaza_identifier,
        start_date=start_date,
        end_date=end_date,
    )
    query += " ORDER BY date, hour, lane"

    with psycopg2.connect(**get_analytics_db_connection_kwargs()) as conn:
        df = pd.read_sql(query, conn, params=params or None)

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["hour"] = df["hour"].astype(str)
    return df
